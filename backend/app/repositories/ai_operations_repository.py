from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.ai_operations import DemandBatchReceipt, DispatchQualityReport
from app.models.store import Store
from app.models.delivery_demand import DeliveryDemand
from app.models.audit_log import AuditLog


class AIOperationsRepository:
    def __init__(self, session: Session):
        self.session = session

    def stores(self):
        return list(self.session.scalars(select(Store).where(Store.is_active.is_(True)).order_by(Store.id)))

    def receipt(self, actor_id, key):
        return self.session.scalar(select(DemandBatchReceipt).where(DemandBatchReceipt.actor_id == actor_id, DemandBatchReceipt.request_key == key))

    def reports(self, plan_id):
        return list(self.session.scalars(select(DispatchQualityReport).where(DispatchQualityReport.plan_id == plan_id).order_by(DispatchQualityReport.id.desc())))

    def report(self, report_id):
        return self.session.get(DispatchQualityReport, report_id)

    def demands(self, ids):
        return list(self.session.scalars(select(DeliveryDemand).where(DeliveryDemand.id.in_(ids)))) if ids else []

    def audit_exists(self, plan_id):
        return self.session.scalar(select(AuditLog.id).where(AuditLog.object_type == "DispatchPlan", AuditLog.object_id == plan_id).limit(1)) is not None

    def add(self, row):
        self.session.add(row)
        self.session.flush()
        return row
