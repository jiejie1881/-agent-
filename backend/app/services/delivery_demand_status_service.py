from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.domain.enums import DeliveryDemandStatus
from app.domain.exceptions import ConflictError, NotFoundError
from app.models.delivery_demand import DeliveryDemand
from app.repositories.delivery_demand_repository import DeliveryDemandRepository


ALLOWED_TRANSITIONS: dict[DeliveryDemandStatus, set[DeliveryDemandStatus]] = {
    DeliveryDemandStatus.PENDING: {
        DeliveryDemandStatus.PLANNED,
        DeliveryDemandStatus.CANCELLED,
    },
    DeliveryDemandStatus.PLANNED: {
        DeliveryDemandStatus.PENDING,
        DeliveryDemandStatus.PUBLISHED,
        DeliveryDemandStatus.CANCELLED,
    },
    DeliveryDemandStatus.PUBLISHED: {
        DeliveryDemandStatus.PENDING,
        DeliveryDemandStatus.DELIVERING,
        DeliveryDemandStatus.CANCELLED,
    },
    DeliveryDemandStatus.DELIVERING: {
        DeliveryDemandStatus.COMPLETED,
        DeliveryDemandStatus.CANCELLED,
    },
    DeliveryDemandStatus.COMPLETED: {
        DeliveryDemandStatus.CANCELLED,
    },
    DeliveryDemandStatus.CANCELLED: set(),
}


class DeliveryDemandStatusService:
    """The only service responsible for changing an existing demand status."""

    def __init__(self, session: Session) -> None:
        self.repository = DeliveryDemandRepository(session)

    @staticmethod
    def validate_initial(status: DeliveryDemandStatus) -> None:
        if status != DeliveryDemandStatus.PENDING:
            raise ConflictError("新建配送需求的状态必须为PENDING")

    def transition(
        self,
        demand: DeliveryDemand,
        target: DeliveryDemandStatus,
    ) -> DeliveryDemand:
        self._validate_transition(demand.status, target)
        demand.status = target
        self.repository.session.add(demand)
        return demand

    def get_many(self, demand_ids: Iterable[int]) -> list[DeliveryDemand]:
        return self.repository.get_many(set(demand_ids))

    def transition_many(
        self,
        demand_ids: Iterable[int],
        target: DeliveryDemandStatus,
        allowed_current: set[DeliveryDemandStatus] | None = None,
    ) -> list[DeliveryDemand]:
        ids = set(demand_ids)
        demands = self.repository.get_many(ids)
        if len(demands) != len(ids):
            raise NotFoundError("部分门店配送需求不存在")

        for demand in demands:
            if allowed_current is not None and demand.status not in allowed_current:
                raise ConflictError(
                    f"需求{demand.id}当前状态{demand.status.value}不允许此操作"
                )
            self._validate_transition(demand.status, target)

        for demand in demands:
            demand.status = target
            self.repository.session.add(demand)
        return demands

    @staticmethod
    def _validate_transition(
        current: DeliveryDemandStatus,
        target: DeliveryDemandStatus,
    ) -> None:
        if current == target:
            return
        if target not in ALLOWED_TRANSITIONS[current]:
            raise ConflictError(
                f"配送需求状态不允许从{current.value}跳转到{target.value}"
            )
