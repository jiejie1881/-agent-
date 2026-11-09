from datetime import date

from sqlalchemy.orm import Session

from app.domain.exceptions import ConflictError, NotFoundError
from app.models.route import Route, RouteTerrainConfig
from app.repositories.route_repository import RouteRepository, RouteTerrainRepository
from app.repositories.terrain_repository import TerrainRepository
from app.schemas.route import (
    RouteCreate,
    RouteTerrainCreate,
    RouteTerrainUpdate,
    RouteUpdate,
)
from app.services.base import BaseService


class RouteService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = RouteRepository(session)

    def list(self, offset: int = 0, limit: int = 20) -> list[Route]:
        return self.repository.list(offset, limit)

    def get(self, route_id: int) -> Route:
        route = self.repository.get(route_id)
        if route is None:
            raise NotFoundError("线路不存在")
        return route

    def create(self, data: RouteCreate, *, commit: bool = True) -> Route:
        self._validate_source(data.model_dump())
        if self.repository.get_by_code(data.code):
            raise ConflictError("线路编码已存在")
        if self.repository.get_by_name(data.name):
            raise ConflictError("线路名称已存在")
        route = Route(**data.model_dump())
        return self._commit(
            lambda: self.repository.add(route), "线路编码或名称已存在", commit=commit
        )

    def update(self, route_id: int, data: RouteUpdate) -> Route:
        route = self.get(route_id)
        updates = data.model_dump(exclude_unset=True)
        self._validate_source({**{key: getattr(route,key) for key in ('distance_km','duration_minutes','route_data_source')}, **updates})
        for field, value in updates.items():
            setattr(route, field, value)
        return self._commit(
            lambda: self.repository.add(route), "线路编码或名称已存在"
        )

    def delete(self, route_id: int) -> None:
        route = self.get(route_id)
        from sqlalchemy import select
        from app.models.vehicle import Vehicle
        if any(v.allowed_route_ids is not None and route_id in v.allowed_route_ids for v in self.session.scalars(select(Vehicle))):
            raise ConflictError('线路已被车辆运行范围引用，不能删除')
        self._commit(lambda: self.repository.delete(route), "线路正在使用，不能删除")

    @staticmethod
    def _validate_source(values):
        if (values.get('distance_km') is not None or values.get('duration_minutes') is not None) and not (values.get('route_data_source') or '').strip():
            raise ConflictError('填写距离或时间必须说明数据来源；系统不自动计算道路距离')


class RouteTerrainService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.route_repository = RouteRepository(session)
        self.terrain_repository = TerrainRepository(session)
        self.repository = RouteTerrainRepository(session)

    def _validate_route(self, route_id: int) -> None:
        if self.route_repository.get(route_id) is None:
            raise NotFoundError("线路不存在")

    def list(self, route_id: int) -> list[RouteTerrainConfig]:
        self._validate_route(route_id)
        return self.repository.list_by_route(route_id)

    def get(self, route_id: int, config_id: int) -> RouteTerrainConfig:
        self._validate_route(route_id)
        config = self.repository.get(config_id)
        if config is None or config.route_id != route_id:
            raise NotFoundError("线路地形配置不存在")
        return config

    def create(self, route_id: int, data: RouteTerrainCreate) -> RouteTerrainConfig:
        self._validate_route(route_id)
        if self.terrain_repository.get(data.terrain_id) is None:
            raise NotFoundError("地形不存在")
        if self.repository.get_by_route_and_date(route_id, data.effective_date):
            raise ConflictError("该线路在此生效日期已有地形配置")
        config = RouteTerrainConfig(route_id=route_id, **data.model_dump())
        return self._commit(
            lambda: self.repository.add(config), "线路生效日期配置重复"
        )

    def get_effective(self, route_id: int, on_date: date) -> RouteTerrainConfig:
        self._validate_route(route_id)
        config = self.repository.get_effective(route_id, on_date)
        if config is None:
            raise NotFoundError("线路在指定日期没有生效的地形配置")
        return config

    def update(
        self, route_id: int, config_id: int, data: RouteTerrainUpdate
    ) -> RouteTerrainConfig:
        config = self.get(route_id, config_id)
        updates = data.model_dump(exclude_unset=True)
        if "terrain_id" in updates and self.terrain_repository.get(
            updates["terrain_id"]
        ) is None:
            raise NotFoundError("地形不存在")
        if "effective_date" in updates:
            duplicate = self.repository.get_by_route_and_date(
                route_id, updates["effective_date"]
            )
            if duplicate is not None and duplicate.id != config_id:
                raise ConflictError("该线路在此生效日期已有地形配置")
        for field, value in updates.items():
            setattr(config, field, value)
        return self._commit(
            lambda: self.repository.add(config), "线路生效日期配置重复"
        )

    def delete(self, route_id: int, config_id: int) -> None:
        config = self.get(route_id, config_id)
        self._commit(
            lambda: self.repository.delete(config), "无法删除线路地形配置"
        )
