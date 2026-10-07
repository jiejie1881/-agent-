from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cargo_category import CargoCategory
from app.models.delivery_demand import DeliveryDemand
from app.repositories.base import BaseRepository


class CargoCategoryRepository(BaseRepository[CargoCategory]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, CargoCategory)

    def get_by_code(self, code: str) -> CargoCategory | None:
        return self.session.scalar(
            select(CargoCategory).where(CargoCategory.code == code)
        )

    def demand_count(self, category_id: int) -> int:
        return self.session.scalar(
            select(func.count(DeliveryDemand.id)).where(
                DeliveryDemand.cargo_category_id == category_id
            )
        ) or 0
