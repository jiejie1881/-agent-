"""Persistent exception handling; resolution never changes delivery facts."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.domain.enums import UserRole, DeliveryStopStatus, DeliveryProofReviewStatus, DeliveryDemandStatus
from app.domain.exceptions import BusinessError, ConflictError, NotFoundError, PermissionDeniedError
from app.models.business_operations import ExceptionCase, ExceptionCaseEvent
from app.models.dispatch_plan import DispatchOrderDetail, DispatchOrder, DeliveryProof
from app.models.delivery_demand import DeliveryDemand
from app.models.user import User
from app.services.audit_log_service import AuditLogService


class ExceptionCaseService:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def authorize(actor: User):
        if actor.role not in {UserRole.ADMIN, UserRole.DISPATCHER} or not actor.is_active:
            raise PermissionDeniedError()

    def _source(self, category: str, object_id: int):
        if category == "FAILED_STOP":
            item = self.session.get(DispatchOrderDetail, object_id)
            if item and item.delivery_status == DeliveryStopStatus.FAILED:
                return f"配送失败：{item.failure_reason.value if item.failure_reason else '未记录原因'}"
        elif category == "MISSING_PROOF":
            item = self.session.get(DispatchOrderDetail, object_id)
            if item and item.delivery_status == DeliveryStopStatus.SIGNED and not item.proofs:
                return "门店已签收但没有回单"
        elif category == "REJECTED_PROOF":
            item = self.session.get(DeliveryProof, object_id)
            if item and item.review_status == DeliveryProofReviewStatus.REJECTED:
                return "回单审核驳回"
        elif category == "UNASSIGNED_DEMAND":
            item = self.session.get(DeliveryDemand, object_id)
            if item and item.status == DeliveryDemandStatus.PENDING:
                return "需求尚未分配"
        elif category == "STATE_CONFLICT":
            item = self.session.get(DispatchOrderDetail, object_id)
            if item and item.dispatch_order.plan.status.value == 'PUBLISHED' and (
                item.quantity != item.delivery_demand.quantity or item.delivery_demand.date != item.dispatch_order.plan.delivery_date
                or item.delivery_demand.status in {DeliveryDemandStatus.PENDING,DeliveryDemandStatus.PLANNED,DeliveryDemandStatus.CANCELLED}):
                return '已发布任务与需求的日期、货量或状态不一致'
        elif category == "VEHICLE_UNAVAILABLE":
            from app.services.dispatch_plan_publication_validator import DispatchPlanPublicationValidator
            from app.services.dispatch_validation_service import DispatchValidationService
            item = self.session.get(DispatchOrder, object_id)
            if item:
                issues = DispatchPlanPublicationValidator(DispatchValidationService(self.session)).validate(item.plan, for_update=False)
                relevant = [i for i in issues if i.get("order_id") == object_id]
                if relevant:
                    return "；".join(str(i["message"]) for i in relevant)
        raise ConflictError("对应业务记录不存在或当前不满足该异常条件")

    def _responsible(self, user_id: int | None):
        if user_id is None:
            return
        user = self.session.get(User, user_id)
        if user is None or not user.is_active or user.role not in {UserRole.ADMIN, UserRole.DISPATCHER}:
            raise BusinessError("责任人必须是启用的管理员或调度员", 422)

    def _approved_replacement(self, proof_id: int) -> bool:
        original=self.session.get(DeliveryProof,proof_id)
        if original is None:
            return False
        rows=self.session.scalars(select(DeliveryProof).where(DeliveryProof.dispatch_order_detail_id==original.dispatch_order_detail_id)).all()
        children={row.replaces_proof_id:row for row in rows if row.replaces_proof_id is not None}
        current=original;seen={current.id}
        while current.id in children:
            current=children[current.id]
            if current.id in seen:
                return False
            seen.add(current.id)
        return current.id != original.id and current.review_status==DeliveryProofReviewStatus.APPROVED

    def create(self, category: str, object_id: int, responsible_user_id: int | None, actor: User):
        self.authorize(actor)
        key = f"{category}:{object_id}"
        existing = self.session.scalar(select(ExceptionCase).where(ExceptionCase.source_key == key))
        if existing:
            return existing
        reason = self._source(category, object_id)
        self._responsible(responsible_user_id)
        item = ExceptionCase(source_key=key, category=category, reason=reason, status="OPEN",
            responsible_user_id=responsible_user_id, revision=1)
        try:
            self.session.add(item)
            self.session.flush()
            self._event(item, actor, None, reason)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            item = self.session.scalar(select(ExceptionCase).where(ExceptionCase.source_key == key))
            if item is None:
                raise ConflictError("异常登记冲突，请刷新")
        except Exception:
            self.session.rollback()
            raise
        return item

    def _event(self, item, actor, before, note):
        self.session.add(ExceptionCaseEvent(case_id=item.id, actor_id=actor.id, before_status=before,
            after_status=item.status, note=note))
        AuditLogService(self.session).add(actor, "EXCEPTION_CASE_CHANGED", "ExceptionCase", item.id,
            {"source_key": item.source_key, "before_status": before, "after_status": item.status,
             "responsible_user_id": item.responsible_user_id, "revision": item.revision, "note": note})

    def update(self, case_id: int, revision: int, status: str, responsible_user_id: int | None, note: str, actor: User):
        self.authorize(actor)
        try:
            item = self.session.scalar(select(ExceptionCase).where(ExceptionCase.id == case_id).with_for_update())
            if item is None:
                raise NotFoundError("异常工单不存在")
            if item.revision != revision:
                raise ConflictError("异常已被他人修改，请刷新后重试")
            if not note.strip():
                raise BusinessError("必须填写处理说明", 422)
            allowed = {"OPEN": {"OPEN", "IN_PROGRESS"}, "IN_PROGRESS": {"IN_PROGRESS", "RESOLVED", "OPEN"},
                "RESOLVED": {"OPEN"}}
            if status not in allowed[item.status]:
                raise ConflictError("异常状态转换不允许")
            self._responsible(responsible_user_id)
            if status in {"IN_PROGRESS", "RESOLVED"} and responsible_user_id is None:
                raise BusinessError("处理或解决异常前必须指定责任人", 422)
            if status == "RESOLVED" and item.category in {"MISSING_PROOF", "REJECTED_PROOF", "UNASSIGNED_DEMAND", "VEHICLE_UNAVAILABLE", "STATE_CONFLICT"}:
                try:
                    self._source(item.category, int(item.source_key.split(":")[1]))
                except ConflictError:
                    pass
                else:
                    if item.category == "REJECTED_PROOF":
                        old_id = int(item.source_key.split(":")[1])
                        if not self._approved_replacement(old_id):
                            raise ConflictError("驳回回单尚无审核通过的补传版本")
                    else:
                        raise ConflictError("业务异常仍然存在，不能关闭工单")
            before = item.status
            item.status, item.responsible_user_id = status, responsible_user_id
            item.resolution = note.strip() if status == "RESOLVED" else None
            item.revision += 1
            self._event(item, actor, before, note.strip())
            self.session.commit()
            return item
        except Exception:
            self.session.rollback()
            raise

    def list(self, actor: User, status: str | None, offset: int, limit: int):
        self.authorize(actor)
        query = select(ExceptionCase).order_by(ExceptionCase.id.desc())
        if status:
            query = query.where(ExceptionCase.status == status)
        return self.session.scalars(query.offset(offset).limit(limit)).all()

    def events(self, case_id: int, actor: User):
        self.authorize(actor)
        if self.session.get(ExceptionCase, case_id) is None:
            raise NotFoundError("异常工单不存在")
        return self.session.scalars(select(ExceptionCaseEvent).where(ExceptionCaseEvent.case_id == case_id)
            .order_by(ExceptionCaseEvent.id)).all()
