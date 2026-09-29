from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.store import Store, StoreRoute
from app.repositories.base import BaseRepository


class StoreRepository(BaseRepository[Store]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Store)

    def get_by_code(self, code: str) -> Store | None:
        return self.session.scalar(select(Store).where(Store.code == code))

    def get_by_name(self, name: str) -> Store | None:
        return self.session.scalar(select(Store).where(Store.name == name))


class StoreRouteRepository(BaseRepository[StoreRoute]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, StoreRoute)

    def get_link(self, store_id: int, route_id: int) -> StoreRoute | None:
        statement = select(StoreRoute).where(
            StoreRoute.store_id == store_id, StoreRoute.route_id == route_id
        )
        return self.session.scalar(statement)

    def list_by_store(self, store_id: int) -> list[StoreRoute]:
        statement = (
            select(StoreRoute)
            .options(joinedload(StoreRoute.route))
            .where(StoreRoute.store_id == store_id)
            .order_by(StoreRoute.id)
        )
        return list(self.session.scalars(statement))
