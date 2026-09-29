from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.terrain import Terrain
from app.repositories.base import BaseRepository


class TerrainRepository(BaseRepository[Terrain]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Terrain)

    def get_by_code(self, code: str) -> Terrain | None:
        return self.session.scalar(select(Terrain).where(Terrain.code == code))

    def get_by_name(self, name: str) -> Terrain | None:
        return self.session.scalar(select(Terrain).where(Terrain.name == name))

    def route_config_count(self, terrain_id: int) -> int:
        from app.models.route import RouteTerrainConfig

        statement = select(func.count(RouteTerrainConfig.id)).where(
            RouteTerrainConfig.terrain_id == terrain_id
        )
        return self.session.scalar(statement) or 0
