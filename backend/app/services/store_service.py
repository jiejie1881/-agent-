from sqlalchemy.orm import Session

from app.domain.exceptions import ConflictError, NotFoundError
from app.models.store import Store, StoreRoute
from app.repositories.route_repository import RouteRepository
from app.repositories.store_repository import StoreRepository, StoreRouteRepository
from app.schemas.store import StoreCreate, StoreUpdate
from app.services.base import BaseService


class StoreService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = StoreRepository(session)

    def list(self, offset: int = 0, limit: int = 20) -> list[Store]:
        return self.repository.list(offset, limit)

    def get(self, store_id: int) -> Store:
        store = self.repository.get(store_id)
        if store is None:
            raise NotFoundError("门店不存在")
        return store

    def create(self, data: StoreCreate) -> Store:
        if self.repository.get_by_code(data.code):
            raise ConflictError("门店编码已存在")
        if self.repository.get_by_name(data.name):
            raise ConflictError("门店名称已存在")
        store = Store(**data.model_dump())
        return self._commit(
            lambda: self.repository.add(store), "门店编码或名称已存在"
        )

    def update(self, store_id: int, data: StoreUpdate) -> Store:
        store = self.get(store_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(store, field, value)
        return self._commit(
            lambda: self.repository.add(store), "门店编码或名称已存在"
        )

    def delete(self, store_id: int) -> None:
        store = self.get(store_id)
        self._commit(lambda: self.repository.delete(store), "门店正在使用，不能删除")


class StoreRouteService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.store_repository = StoreRepository(session)
        self.route_repository = RouteRepository(session)
        self.repository = StoreRouteRepository(session)

    def _get_store(self, store_id: int) -> Store:
        store = self.store_repository.get(store_id)
        if store is None:
            raise NotFoundError("门店不存在")
        return store

    def list(self, store_id: int) -> list[StoreRoute]:
        self._get_store(store_id)
        return self.repository.list_by_store(store_id)

    def add(self, store_id: int, route_id: int) -> StoreRoute:
        self._get_store(store_id)
        if self.route_repository.get(route_id) is None:
            raise NotFoundError("线路不存在")
        if self.repository.get_link(store_id, route_id):
            raise ConflictError("门店已关联该线路")
        link = StoreRoute(store_id=store_id, route_id=route_id)
        return self._commit(
            lambda: self.repository.add(link), "门店已关联该线路"
        )

    def remove(self, store_id: int, route_id: int) -> None:
        self._get_store(store_id)
        link = self.repository.get_link(store_id, route_id)
        if link is None:
            raise NotFoundError("门店线路关联不存在")
        self._commit(lambda: self.repository.delete(link), "无法删除门店线路关联")

