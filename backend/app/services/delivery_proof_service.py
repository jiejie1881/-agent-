from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.storage import upload_root
from app.domain.enums import DeliveryProofReviewStatus, DeliveryStopStatus, UserRole
from app.domain.exceptions import BusinessError, ConflictError, NotFoundError, PermissionDeniedError
from app.domain.permissions import Permission, has_permission
from app.models.dispatch_plan import DeliveryProofReview
from app.repositories.delivery_proof_repository import DeliveryProofRepository
from app.services.audit_log_service import AuditLogService


class DeliveryProofService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = DeliveryProofRepository(session)

    @staticmethod
    def authorize_read(proof, actor):
        if actor.role == UserRole.DRIVER:
            if proof.stop.dispatch_order.actual_driver_id != actor.id:
                raise NotFoundError("配送回单不存在")
        elif not has_permission(actor.role, Permission.READ):
            raise PermissionDeniedError()

    def image(self, actor, *, proof_id=None, filename=None):
        proof = self.repository.get(proof_id) if proof_id is not None else self.repository.by_path(f"delivery-proofs/{filename}")
        if proof is None:
            raise NotFoundError("配送回单不存在")
        self.authorize_read(proof, actor)
        root = upload_root().resolve()
        path = (root / proof.file_path).resolve()
        if not path.is_relative_to(root / "delivery-proofs") or not path.is_file():
            raise NotFoundError("配送回单文件不存在")
        return path, proof.content_type

    def review(self, proof_id, data, actor):
        if actor.role != UserRole.ADMIN:
            raise PermissionDeniedError("只有管理员可以审核回单")
        proof = self.repository.get(proof_id)
        if proof is None:
            raise NotFoundError("配送回单不存在")
        self.repository.lock_stop(proof.dispatch_order_detail_id)
        rows = self.repository.list_for_stop(proof.dispatch_order_detail_id)
        proof = next(row for row in rows if row.id == proof_id)
        if proof.stop.delivery_status != DeliveryStopStatus.SIGNED:
            raise ConflictError("门店签收后才能审核回单")
        if proof.review_status != DeliveryProofReviewStatus.PENDING or any(row.replaces_proof_id == proof.id for row in rows):
            raise ConflictError("该回单已审核或已被补传替代，不允许重复审核")
        try:
            proof.review_status = data.decision
            self.repository.add(DeliveryProofReview(
                proof_id=proof.id, reviewer_id=actor.id, reviewer_username=actor.username,
                decision=data.decision, reason=data.reason,
            ))
            AuditLogService(self.session).add(actor, "DELIVERY_PROOF_REVIEWED", "DeliveryProof", proof.id,
                {"decision": data.decision.value, "reason": data.reason,
                 "order_id": proof.stop.dispatch_order_id, "stop_id": proof.dispatch_order_detail_id})
            self.session.commit()
            self.session.refresh(proof)
            return proof
        except BusinessError:
            self.session.rollback()
            raise
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("回单审核保存失败") from exc
