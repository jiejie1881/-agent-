from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.enums import DeliveryPeriod
from app.models.delivery_demand import DeliveryDemand
from app.repositories.base import BaseRepository


class DeliveryDemandRepository(BaseRepository[DeliveryDemand]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DeliveryDemand)

    def get(self, entity_id: int) -> DeliveryDemand | None:
        statement = (
            select(DeliveryDemand)
            .options(
                joinedload(DeliveryDemand.store),
                joinedload(DeliveryDemand.cargo_category),
            )
            .where(DeliveryDemand.id == entity_id)
        )
        return self.session.scalar(statement)

    def list_filtered(
        self,
        demand_date: date | None,
        store_id: int | None,
        period: DeliveryPeriod | None,
        offset: int,
        limit: int,
    ) -> list[DeliveryDemand]:
        statement = select(DeliveryDemand).options(
            joinedload(DeliveryDemand.store),
            joinedload(DeliveryDemand.cargo_category),
        )
        if demand_date is not None:
            statement = statement.where(DeliveryDemand.date == demand_date)
        if store_id is not None:
            statement = statement.where(DeliveryDemand.store_id == store_id)
        if period is not None:
            statement = statement.where(DeliveryDemand.period == period)
        statement = statement.order_by(
            DeliveryDemand.date.desc(), DeliveryDemand.id
        ).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def get_by_business_key(
        self, demand_date: date, store_id: int, period: DeliveryPeriod
    ) -> DeliveryDemand | None:
        statement = select(DeliveryDemand).where(
            DeliveryDemand.date == demand_date,
            DeliveryDemand.store_id == store_id,
            DeliveryDemand.period == period,
        )
        return self.session.scalar(statement)

    def get_many(self, demand_ids: set[int]) -> list[DeliveryDemand]:
        if not demand_ids:
            return []
        statement = select(DeliveryDemand).where(
            DeliveryDemand.id.in_(demand_ids)
        )
        return list(self.session.scalars(statement))
