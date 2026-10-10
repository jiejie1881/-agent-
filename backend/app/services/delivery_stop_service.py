from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.storage import delivery_proof_directory
from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryStopStatus,
    DeliveryProofReviewStatus,
)
from app.domain.exceptions import BusinessError, ConflictError, NotFoundError
from app.models.dispatch_plan import DeliveryProof, DispatchOrder, DispatchOrderDetail
from app.models.user import User
from app.repositories.driver_task_repository import DriverTaskRepository
from app.repositories.delivery_proof_repository import DeliveryProofRepository
from app.schemas.driver import DeliveryStopFailRequest, DeliveryStopSignRequest
from app.services.audit_log_service import AuditAction, AuditLogService


TERMINAL_STOP_STATUSES = {
    DeliveryStopStatus.SIGNED,
    DeliveryStopStatus.FAILED,
}

IMAGE_FORMATS = {
    "image/jpeg": (".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/png": (".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (
        ".webp",
        lambda data: len(data) >= 12
        and data.startswith(b"RIFF")
        and data[8:12] == b"WEBP",
    ),
}


class DeliveryStopService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = DriverTaskRepository(session)

    def get_owned_stop(
        self, task_id: int, stop_id: int, driver_user_id: int
    ) -> tuple[DispatchOrder, DispatchOrderDetail]:
        order = self.repository.get_for_driver(task_id, driver_user_id)
        if order is None:
            raise NotFoundError("配送任务不存在")
        stop = next((item for item in order.details if item.id == stop_id), None)
        if stop is None:
            raise NotFoundError("配送停靠点不存在")
        return order, stop

    def arrive(
        self, task_id: int, stop_id: int, actor: User
    ) -> DispatchOrderDetail:
        order, stop = self.get_owned_stop(task_id, stop_id, actor.id)
        self._require_task_delivering(order)
        if stop.delivery_status != DeliveryStopStatus.PENDING:
            raise ConflictError(
                f"停靠点当前状态{stop.delivery_status.value}不允许到店"
            )
        stop.delivery_status = DeliveryStopStatus.ARRIVED
        stop.arrived_at = datetime.now(timezone.utc)
        return self._commit_stop(
            order, stop, actor, AuditAction.DELIVERY_STOP_ARRIVED
        )

    def sign(
        self,
        task_id: int,
        stop_id: int,
        data: DeliveryStopSignRequest,
        actor: User,
    ) -> DispatchOrderDetail:
        order, stop = self.get_owned_stop(task_id, stop_id, actor.id)
        self._require_task_delivering(order)
        if stop.delivery_status != DeliveryStopStatus.ARRIVED:
            raise ConflictError("只有ARRIVED停靠点可以签收")
        stop.delivery_status = DeliveryStopStatus.SIGNED
        stop.signed_at = datetime.now(timezone.utc)
        stop.receiver_name = data.receiver_name
        stop.receiver_phone = data.receiver_phone
        stop.driver_remark = data.remark
        stop.failure_reason = None
        return self._commit_stop(
            order,
            stop,
            actor,
            AuditAction.DELIVERY_STOP_SIGNED,
            {"receiver_name": data.receiver_name},
        )

    def fail(
        self,
        task_id: int,
        stop_id: int,
        data: DeliveryStopFailRequest,
        actor: User,
    ) -> DispatchOrderDetail:
        order, stop = self.get_owned_stop(task_id, stop_id, actor.id)
        self._require_task_delivering(order)
        if stop.delivery_status not in {
            DeliveryStopStatus.PENDING,
            DeliveryStopStatus.ARRIVED,
        }:
            raise ConflictError(
                f"停靠点当前状态{stop.delivery_status.value}不允许标记失败"
            )
        stop.delivery_status = DeliveryStopStatus.FAILED
        stop.failure_reason = data.failure_reason
        stop.driver_remark = data.remark
        stop.receiver_name = None
        stop.receiver_phone = None
        stop.signed_at = None
        return self._commit_stop(
            order,
            stop,
            actor,
            AuditAction.DELIVERY_STOP_FAILED,
            {"failure_reason": data.failure_reason.value},
        )

    def upload_proof(
        self,
        task_id: int,
        stop_id: int,
        content_type: str,
        content: bytes,
        actor: User,
        replaces_proof_id: int | None = None,
    ) -> DeliveryProof:
        order, stop = self.get_owned_stop(task_id, stop_id, actor.id)
        repository = DeliveryProofRepository(self.session)
        repository.lock_stop(stop.id)
        proofs = repository.list_for_stop(stop.id)
        replaced_ids = {proof.replaces_proof_id for proof in proofs if proof.replaces_proof_id}
        if replaces_proof_id is not None:
            previous = next((proof for proof in proofs if proof.id == replaces_proof_id), None)
            if previous is None:
                raise NotFoundError("待补传回单不属于此门店")
            if previous.review_status != DeliveryProofReviewStatus.REJECTED or previous.id in replaced_ids:
                raise ConflictError("只能补传尚未被替代的驳回回单")
            if stop.delivery_status != DeliveryStopStatus.SIGNED or any(
                detail.delivery_demand.status not in {DeliveryDemandStatus.DELIVERING, DeliveryDemandStatus.COMPLETED}
                for detail in order.details
            ):
                raise ConflictError("当前任务不允许补传回单")
        else:
            self._require_task_delivering(order)
        if stop.delivery_status == DeliveryStopStatus.PENDING:
            raise ConflictError("司机到店后才能上传配送回单")
        proof_count = sum(proof.id not in replaced_ids for proof in proofs)
        if replaces_proof_id is None and proof_count >= 3:
            raise ConflictError("每个门店最多上传3张配送回单")

        normalized_type = content_type.lower().split(";", 1)[0].strip()
        image_format = IMAGE_FORMATS.get(normalized_type)
        if image_format is None or not image_format[1](content):
            raise ConflictError("仅支持有效的JPEG、PNG或WEBP图片")
        if len(content) > get_settings().delivery_proof_max_bytes:
            raise ConflictError("配送回单图片超过大小限制")

        filename = f"{uuid4().hex}{image_format[0]}"
        relative_path = Path("delivery-proofs") / filename
        destination = delivery_proof_directory() / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        written = False
        try:
            destination.write_bytes(content)
            written = True
            proof = DeliveryProof(
                dispatch_order_detail_id=stop.id,
                file_path=relative_path.as_posix(),
                url=f"/uploads/{relative_path.as_posix()}",
                content_type=normalized_type,
                size_bytes=len(content),
                replaces_proof_id=replaces_proof_id,
            )
            self.session.add(proof)
            self.session.flush()
            AuditLogService(self.session).add(
                actor,
                AuditAction.DELIVERY_PROOF_UPLOADED,
                "DispatchOrderDetail",
                stop.id,
                {
                    "plan_id": order.plan_id,
                    "order_id": order.id,
                    "proof_id": proof.id,
                    "content_type": normalized_type,
                    "size_bytes": len(content),
                    "replaces_proof_id": replaces_proof_id,
                },
            )
            self.session.commit()
            self.session.refresh(proof)
            return proof
        except BusinessError:
            self.session.rollback()
            if written:
                destination.unlink(missing_ok=True)
            raise
        except (SQLAlchemyError, OSError) as exc:
            self.session.rollback()
            if written:
                destination.unlink(missing_ok=True)
            raise ConflictError("配送回单保存失败") from exc

    def _commit_stop(
        self,
        order: DispatchOrder,
        stop: DispatchOrderDetail,
        actor: User,
        action: str,
        extra_changes: dict[str, object] | None = None,
    ) -> DispatchOrderDetail:
        try:
            self.session.add(stop)
            changes = {
                "plan_id": order.plan_id,
                "order_id": order.id,
                "delivery_status": stop.delivery_status.value,
            }
            if extra_changes:
                changes.update(extra_changes)
            AuditLogService(self.session).add(
                actor, action, "DispatchOrderDetail", stop.id, changes
            )
            self.session.commit()
            return stop
        except BusinessError:
            self.session.rollback()
            raise
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("配送停靠点状态更新失败") from exc

    @staticmethod
    def _require_task_delivering(order: DispatchOrder) -> None:
        if not order.details or any(
            item.delivery_demand.status != DeliveryDemandStatus.DELIVERING
            for item in order.details
        ):
            raise ConflictError("任务尚未开始配送或当前状态不允许门店操作")
