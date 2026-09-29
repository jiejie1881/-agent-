from sqlalchemy import select
from datetime import date

from sqlalchemy.orm import Session, joinedload

from app.models.route import Route, RouteTerrainConfig
from app.repositories.base import BaseRepository


class RouteRepository(BaseRepository[Route]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Route)

    def get_by_code(self, code: str) -> Route | None:
        return self.session.scalar(select(Route).where(Route.code == code))

    def get_by_name(self, name: str) -> Route | None:
        return self.session.scalar(select(Route).where(Route.name == name))


class RouteTerrainRepository(BaseRepository[RouteTerrainConfig]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, RouteTerrainConfig)

    def get_by_route_and_date(
        self, route_id: int, effective_date: date
    ) -> RouteTerrainConfig | None:
        statement = select(RouteTerrainConfig).where(
            RouteTerrainConfig.route_id == route_id,
            RouteTerrainConfig.effective_date == effective_date,
        )
        return self.session.scalar(statement)

    def list_by_route(self, route_id: int) -> list[RouteTerrainConfig]:
        statement = (
            select(RouteTerrainConfig)
            .options(joinedload(RouteTerrainConfig.terrain))
            .where(RouteTerrainConfig.route_id == route_id)
            .order_by(RouteTerrainConfig.effective_date.desc())
        )
        return list(self.session.scalars(statement))

    def get_effective(
        self, route_id: int, on_date: date
    ) -> RouteTerrainConfig | None:
        statement = (
            select(RouteTerrainConfig)
            .options(joinedload(RouteTerrainConfig.terrain))
            .where(
                RouteTerrainConfig.route_id == route_id,
                RouteTerrainConfig.effective_date <= on_date,
            )
            .order_by(
                RouteTerrainConfig.effective_date.desc(),
                RouteTerrainConfig.updated_at.desc(),
            )
            .limit(1)
        )
        return self.session.scalar(statement)
