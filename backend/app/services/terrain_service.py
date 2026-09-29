from sqlalchemy.orm import Session

from app.domain.exceptions import ConflictError, NotFoundError
from app.models.terrain import Terrain
from app.repositories.terrain_repository import TerrainRepository
from app.schemas.terrain import TerrainCreate, TerrainUpdate
from app.services.base import BaseService


class TerrainService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = TerrainRepository(session)

    def list(self, offset: int = 0, limit: int = 20) -> list[Terrain]:
        return self.repository.list(offset, limit)

    def get(self, terrain_id: int) -> Terrain:
        terrain = self.repository.get(terrain_id)
        if terrain is None:
            raise NotFoundError("地形不存在")
        return terrain

    def create(self, data: TerrainCreate) -> Terrain:
        if self.repository.get_by_code(data.code):
            raise ConflictError("地形编码已存在")
        if self.repository.get_by_name(data.name):
            raise ConflictError("地形名称已存在")
        terrain = Terrain(**data.model_dump())
        return self._commit(
            lambda: self.repository.add(terrain), "地形编码或名称已存在"
        )

    def update(self, terrain_id: int, data: TerrainUpdate) -> Terrain:
        terrain = self.get(terrain_id)
        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(terrain, field, value)
        return self._commit(
            lambda: self.repository.add(terrain), "地形编码或名称已存在"
        )

    def delete(self, terrain_id: int) -> None:
        terrain = self.get(terrain_id)
        if self.repository.route_config_count(terrain_id):
            raise ConflictError("地形已被线路使用，不能删除")
        self._commit(
            lambda: self.repository.delete(terrain), "地形已被线路使用，不能删除"
        )
