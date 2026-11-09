import hashlib
import json
from sqlalchemy.exc import IntegrityError
from app.domain.enums import UserRole
from app.domain.exceptions import BusinessError, ConflictError, PermissionDeniedError
from app.models.ai_operations import DemandBatchReceipt
from app.repositories.ai_operations_repository import AIOperationsRepository
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.audit_log_service import AuditLogService


class DemandBatchService:
    def __init__(self, session):
        self.session = session
        self.repository = AIOperationsRepository(session)

    def confirm(self, data, actor):
        if actor.role != UserRole.ADMIN:
            raise PermissionDeniedError("AI批量确认仅允许管理员")
        if not data.confirmed:
            raise BusinessError("请先确认所有配送字段", 422, "AI_DEMAND_CONFIRM_REQUIRED")
        key = str(data.request_key)
        digest = hashlib.sha256(json.dumps([i.model_dump(mode='json') for i in data.items], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        def replay(receipt):
            if receipt.payload_hash != digest:
                raise ConflictError("该请求标识已用于不同内容，请勿复用")
            return {"demand_ids": receipt.demand_ids, "replayed": True}
        existing = self.repository.receipt(actor.id, key)
        if existing: return replay(existing)
        try:
            receipt = self.repository.add(DemandBatchReceipt(actor_id=actor.id, request_key=key, payload_hash=digest, demand_ids=[]))
            service = DeliveryDemandService(self.session)
            ids = [service.create(item, actor, commit=False).id for item in data.items]
            receipt.demand_ids = ids
            AuditLogService(self.session).add(actor, "AI_DEMAND_BATCH_CONFIRMED", "DemandBatchReceipt", receipt.id, {"demand_ids": ids})
            self.session.commit()
            return {"demand_ids": ids, "replayed": False}
        except IntegrityError:
            self.session.rollback()
            existing = self.repository.receipt(actor.id, key)
            if existing: return replay(existing)
            raise ConflictError("批量需求存在重复或数据库约束冲突；整批未创建") from None
        except BusinessError:
            self.session.rollback()
            raise
