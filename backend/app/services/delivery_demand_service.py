from datetime import date

from sqlalchemy.orm import Session

from app.domain.enums import DeliveryDemandStatus, DeliveryPeriod
from app.domain.delivery_demand_policy import (
    can_edit_delivery_demand_core_fields,
)
from app.domain.exceptions import (
    ConflictError,
    DemandLockedByDispatchError,
    NotFoundError,
)
from app.models.delivery_demand import DeliveryDemand
from app.repositories.delivery_demand_repository import DeliveryDemandRepository
from app.repositories.store_repository import StoreRepository
from app.schemas.delivery_demand import DeliveryDemandCreate, DeliveryDemandUpdate
from app.services.base import BaseService
from app.services.delivery_demand_status_service import DeliveryDemandStatusService
from app.models.user import User
from app.services.audit_log_service import AuditAction, AuditLogService


class DeliveryDemandService(BaseService):
    CORE_BUSINESS_FIELDS = frozenset({"date", "store_id", "period", "quantity"})

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = DeliveryDemandRepository(session)
        self.store_repository = StoreRepository(session)
        self.status_service = DeliveryDemandStatusService(session)

    def list(
        self,
        demand_date: date | None,
        store_id: int | None,
        period: DeliveryPeriod | None,
        offset: int,
        limit: int,
    ) -> list[DeliveryDemand]:
        return self.repository.list_filtered(
            demand_date, store_id, period, offset, limit
        )

    def get(self, demand_id: int) -> DeliveryDemand:
        demand = self.repository.get(demand_id)
        if demand is None:
            raise NotFoundError("门店配送需求不存在")
        return demand

    def _validate_store(self, store_id: int) -> None:
        if self.store_repository.get(store_id) is None:
            raise NotFoundError("门店不存在")

    def create(self, data: DeliveryDemandCreate, actor: User) -> DeliveryDemand:
        self.status_service.validate_initial(data.status)
        self._validate_store(data.store_id)
        if self.repository.get_by_business_key(
            data.date, data.store_id, data.period
        ):
            raise ConflictError("该门店当天同一时段已有配送需求")
        demand = DeliveryDemand(**data.model_dump())
        def action() -> DeliveryDemand:
            created = self.repository.add(demand)
            AuditLogService(self.session).add(
                actor,
                AuditAction.DELIVERY_DEMAND_CREATED,
                "DeliveryDemand",
                created.id,
                {"after": data.model_dump()},
            )
            return created

        return self._commit(
            action,
            "该门店当天同一时段已有配送需求",
        )

    def update(
        self, demand_id: int, data: DeliveryDemandUpdate, actor: User
    ) -> DeliveryDemand:
        demand = self.get(demand_id)
        updates = data.model_dump(exclude_unset=True)
        before = {field: getattr(demand, field) for field in updates}
        if (
            not can_edit_delivery_demand_core_fields(demand.status)
            and self.CORE_BUSINESS_FIELDS.intersection(updates)
        ):
            raise DemandLockedByDispatchError(demand.status.value)
        demand_date = updates.get("date", demand.date)
        store_id = updates.get("store_id", demand.store_id)
        period = updates.get("period", demand.period)
        self._validate_store(store_id)
        duplicate = self.repository.get_by_business_key(
            demand_date, store_id, period
        )
        if duplicate is not None and duplicate.id != demand_id:
            raise ConflictError("该门店当天同一时段已有配送需求")
        for field, value in updates.items():
            setattr(demand, field, value)
        def action() -> DeliveryDemand:
            updated = self.repository.add(demand)
            AuditLogService(self.session).add(
                actor,
                AuditAction.DELIVERY_DEMAND_UPDATED,
                "DeliveryDemand",
                updated.id,
                {
                    "before": before,
                    "after": {
                        field: getattr(updated, field) for field in updates
                    },
                },
            )
            return updated

        return self._commit(
            action,
            "该门店当天同一时段已有配送需求",
        )

    def cancel(self, demand_id: int) -> DeliveryDemand:
        demand = self.get(demand_id)
        self.status_service.transition(
            demand, DeliveryDemandStatus.CANCELLED
        )
        return self._commit(
            lambda: self.repository.add(demand), "取消配送需求失败"
        )

    def delete(self, demand_id: int) -> None:
        demand = self.get(demand_id)
        self._commit(
            lambda: self.repository.delete(demand), "无法删除门店配送需求"
        )
