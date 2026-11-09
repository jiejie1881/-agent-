import hashlib
import json
import os
import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.storage import delivery_proof_directory
from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryProofReviewStatus,
    DeliveryStopStatus,
)
from app.domain.exceptions import BusinessError, ConflictError, NotFoundError
from app.models.dispatch_plan import DeliveryProof, DispatchOrder, DispatchOrderDetail
from app.models.driver_operation import DriverOperationReceipt
from app.models.user import User
from app.repositories.delivery_proof_repository import DeliveryProofRepository
from app.repositories.driver_task_repository import DriverTaskRepository
from app.schemas.driver import DeliveryStopFailRequest, DeliveryStopSignRequest
from app.services.audit_log_service import AuditAction, AuditLogService

TERMINAL_STOP_STATUSES = {
    DeliveryStopStatus.SIGNED,
    DeliveryStopStatus.FAILED,
}

IMAGE_FORMATS = {
    "image/jpeg": (".jpg", "JPEG"),
    "image/png": (".png", "PNG"),
    "image/webp": (".webp", "WEBP"),
}
MAX_PROOF_PIXELS = 24_000_000
MAX_PROOF_SIDE = 12_000


def validate_proof_image(content: bytes, expected_format: str) -> None:
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != expected_format or min(image.size) < 1:
                raise ValueError("image format mismatch")
            if max(image.size) > MAX_PROOF_SIDE or image.width * image.height > MAX_PROOF_PIXELS:
                raise ValueError("image dimensions exceed limit")
            image.verify()
        # verify() checks the file structure; load() also decodes pixel data.
        with Image.open(BytesIO(content)) as image:
            image.load()
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ConflictError("仅支持有效的JPEG、PNG或WEBP图片") from exc


class DeliveryStopService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = DriverTaskRepository(session)

    def _prepare_operation(self, task_id, stop_id, actor, key, operation, parameters):
        order, stop = self.get_owned_stop(task_id, stop_id, actor.id)
        # All stop writes serialize, including old clients without a key.
        DeliveryProofRepository(self.session).lock_stop(stop.id)
        if key is None:
            return order, stop, None, None
        if not re.fullmatch('[a-f0-9]{32}',key):
            raise ConflictError('幂等键必须为32位小写十六进制字符')
        fingerprint=hashlib.sha256(json.dumps([task_id,stop_id,operation,parameters],
            ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        existing=self.session.scalar(select(DriverOperationReceipt).where(
            DriverOperationReceipt.actor_id==actor.id,DriverOperationReceipt.request_key==key
        ).with_for_update())
        if existing is not None:
            if existing.request_sha256!=fingerprint:
                raise ConflictError('相同幂等键不能用于不同业务参数')
            self.session.commit()  # Read-only replay: release the stop/key locks now.
            return order,stop,None,existing
        receipt=DriverOperationReceipt(actor_id=actor.id,request_key=key,operation=operation,
                                       stop_id=stop.id,request_sha256=fingerprint)
        return order,stop,receipt,None

    def operation_status(self,key,actor):
        receipt=self.session.scalar(select(DriverOperationReceipt).where(
            DriverOperationReceipt.actor_id==actor.id,DriverOperationReceipt.request_key==key))
        if receipt is None:
            raise NotFoundError('操作成功凭据不存在，结果仍需核对')
        stop=self.session.get(DispatchOrderDetail,receipt.stop_id)
        order,_=self.get_owned_stop(stop.dispatch_order_id,stop.id,actor.id)
        return {'status':'SUCCEEDED','operation':receipt.operation,'task_id':order.id,
                'stop_id':stop.id,'proof_id':receipt.proof_id}

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
        self, task_id: int, stop_id: int, actor: User, idempotency_key: str | None = None
    ) -> DispatchOrderDetail:
        order, stop, receipt, existing = self._prepare_operation(task_id,stop_id,actor,idempotency_key,'ARRIVE',{})
        if existing is not None:
            return stop
        self._require_task_delivering(order)
        if stop.delivery_status != DeliveryStopStatus.PENDING:
            raise ConflictError(
                f"停靠点当前状态{stop.delivery_status.value}不允许到店"
            )
        stop.delivery_status = DeliveryStopStatus.ARRIVED
        stop.arrived_at = datetime.now(UTC)
        return self._commit_stop(
            order, stop, actor, AuditAction.DELIVERY_STOP_ARRIVED, receipt=receipt
        )

    def sign(
        self,
        task_id: int,
        stop_id: int,
        data: DeliveryStopSignRequest,
        actor: User,
        idempotency_key: str | None = None,
    ) -> DispatchOrderDetail:
        order, stop, receipt, existing = self._prepare_operation(task_id,stop_id,actor,idempotency_key,'SIGN',data.model_dump(mode='json'))
        if existing is not None:
            return stop
        self._require_task_delivering(order)
        if stop.delivery_status != DeliveryStopStatus.ARRIVED:
            raise ConflictError("只有ARRIVED停靠点可以签收")
        stop.delivery_status = DeliveryStopStatus.SIGNED
        stop.signed_at = datetime.now(UTC)
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
            receipt=receipt,
        )

    def fail(
        self,
        task_id: int,
        stop_id: int,
        data: DeliveryStopFailRequest,
        actor: User,
        idempotency_key: str | None = None,
    ) -> DispatchOrderDetail:
        order, stop, receipt, existing = self._prepare_operation(task_id,stop_id,actor,idempotency_key,'FAIL',data.model_dump(mode='json'))
        if existing is not None:
            return stop
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
            receipt=receipt,
        )

    def upload_proof(
        self,
        task_id: int,
        stop_id: int,
        content_type: str,
        content: bytes,
        actor: User,
        replaces_proof_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> DeliveryProof:
        normalized_type = content_type.lower().split(";", 1)[0].strip()
        order, stop, receipt, existing = self._prepare_operation(task_id,stop_id,actor,idempotency_key,'UPLOAD',
            {'sha256':hashlib.sha256(content).hexdigest(),'content_type':normalized_type,'replaces_proof_id':replaces_proof_id})
        if existing is not None:
            return self.session.get(DeliveryProof,existing.proof_id)
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
        if image_format is None:
            raise ConflictError("仅支持有效的JPEG、PNG或WEBP图片")
        if len(content) > get_settings().delivery_proof_max_bytes:
            raise ConflictError("配送回单图片超过大小限制")
        validate_proof_image(content, image_format[1])

        file_id=uuid4().hex if receipt is None else hashlib.sha256(
            f'{actor.id}:{idempotency_key}:{receipt.request_sha256}'.encode()).hexdigest()[:32]
        filename = f"{file_id}{image_format[0]}"
        relative_path = Path("delivery-proofs") / filename
        destination = delivery_proof_directory() / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        written = False
        committing = False
        try:
            try:
                with destination.open('xb') as stream:
                    written = True
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                # Exact retry after an unknown DB commit result reuses its
                # immutable bytes; it never overwrites someone else's evidence.
                if receipt is None or destination.read_bytes()!=content:
                    raise ConflictError('回单文件指纹不一致，请核对存储') from None
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
            if receipt is not None:
                receipt.proof_id=proof.id
                self.session.add(receipt)
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
            committing = True
            self.session.commit()
            return proof
        except BusinessError:
            self.session.rollback()
            if written and not committing:
                destination.unlink(missing_ok=True)
            raise
        except (SQLAlchemyError, OSError) as exc:
            self.session.rollback()
            if written and (not committing or isinstance(exc,IntegrityError)):
                destination.unlink(missing_ok=True)
            raise ConflictError("配送回单保存失败") from exc
        except Exception:
            self.session.rollback()
            if written and not committing:
                destination.unlink(missing_ok=True)
            raise

    def _commit_stop(
        self,
        order: DispatchOrder,
        stop: DispatchOrderDetail,
        actor: User,
        action: str,
        extra_changes: dict[str, object] | None = None,
        receipt: DriverOperationReceipt | None = None,
    ) -> DispatchOrderDetail:
        try:
            self.session.add(stop)
            if receipt is not None:
                self.session.add(receipt)
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
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConflictError("配送停靠点状态更新失败") from exc
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _require_task_delivering(order: DispatchOrder) -> None:
        if not order.details or any(
            item.delivery_demand.status != DeliveryDemandStatus.DELIVERING
            for item in order.details
        ):
            raise ConflictError("任务尚未开始配送或当前状态不允许门店操作")
