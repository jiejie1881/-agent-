from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.exceptions import ConflictError, NotFoundError
from app.models.vehicle import Vehicle, VehicleType, VehicleTypeTerrainPermission
from app.repositories.terrain_repository import TerrainRepository
from app.repositories.vehicle_repository import (
    VehicleRepository,
    VehicleTypeRepository,
    VehicleTypeTerrainPermissionRepository,
)
from app.schemas.vehicle import (
    VehicleCreate,
    VehicleTypeCreate,
    VehicleTypeUpdate,
    VehicleUpdate,
)
from app.services.base import BaseService


class VehicleTypeService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = VehicleTypeRepository(session)

    def list(self, offset: int = 0, limit: int = 20) -> list[VehicleType]:
        return self.repository.list(offset, limit)

    def get(self, vehicle_type_id: int) -> VehicleType:
        vehicle_type = self.repository.get(vehicle_type_id)
        if vehicle_type is None:
            raise NotFoundError("车辆类型不存在")
        return vehicle_type

    @staticmethod
    def _validate_load_range(min_load: Decimal, max_load: Decimal) -> None:
        if min_load > max_load:
            raise ConflictError("最低载重量不能大于最高载重量")

    def create(self, data: VehicleTypeCreate) -> VehicleType:
        if self.repository.get_by_code(data.code):
            raise ConflictError("车辆类型编码已存在")
        if self.repository.get_by_name(data.name):
            raise ConflictError("车辆类型名称已存在")
        vehicle_type = VehicleType(**data.model_dump())
        return self._commit(
            lambda: self.repository.add(vehicle_type), "车辆类型编码或名称已存在"
        )

    def update(self, vehicle_type_id: int, data: VehicleTypeUpdate) -> VehicleType:
        vehicle_type = self.get(vehicle_type_id)
        updates = data.model_dump(exclude_unset=True)
        min_load = updates.get("min_load", vehicle_type.min_load)
        max_load = updates.get("max_load", vehicle_type.max_load)
        self._validate_load_range(min_load, max_load)
        for field, value in updates.items():
            setattr(vehicle_type, field, value)
        return self._commit(
            lambda: self.repository.add(vehicle_type), "车辆类型编码或名称已存在"
        )

    def delete(self, vehicle_type_id: int) -> None:
        vehicle_type = self.get(vehicle_type_id)
        if self.repository.vehicle_count(vehicle_type_id):
            raise ConflictError("车辆类型已被车辆使用，不能删除")
        self._commit(
            lambda: self.repository.delete(vehicle_type), "车辆类型正在使用，不能删除"
        )


class VehicleService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = VehicleRepository(session)
        self.vehicle_type_repository = VehicleTypeRepository(session)

    def list(self, offset: int = 0, limit: int = 20) -> list[Vehicle]:
        return self.repository.list(offset, limit)

    def get(self, vehicle_id: int) -> Vehicle:
        vehicle = self.repository.get(vehicle_id)
        if vehicle is None:
            raise NotFoundError("车辆不存在")
        return vehicle

    def _validate_vehicle_type(self, vehicle_type_id: int) -> None:
        if self.vehicle_type_repository.get(vehicle_type_id) is None:
            raise NotFoundError("车辆类型不存在")

    def create(self, data: VehicleCreate) -> Vehicle:
        self._validate_vehicle_type(data.vehicle_type_id)
        if self.repository.get_by_code(data.code):
            raise ConflictError("车辆编码已存在")
        if self.repository.get_by_plate_number(data.plate_number):
            raise ConflictError("车牌号已存在")
        vehicle = Vehicle(**data.model_dump())
        return self._commit(
            lambda: self.repository.add(vehicle), "车辆编码或车牌号已存在"
        )

    def update(self, vehicle_id: int, data: VehicleUpdate) -> Vehicle:
        vehicle = self.get(vehicle_id)
        updates = data.model_dump(exclude_unset=True)
        if "vehicle_type_id" in updates:
            self._validate_vehicle_type(updates["vehicle_type_id"])
        for field, value in updates.items():
            setattr(vehicle, field, value)
        return self._commit(
            lambda: self.repository.add(vehicle), "车辆编码或车牌号已存在"
        )

    def delete(self, vehicle_id: int) -> None:
        vehicle = self.get(vehicle_id)
        self._commit(lambda: self.repository.delete(vehicle), "车辆正在使用，不能删除")


class VehicleTypeTerrainPermissionService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.vehicle_type_repository = VehicleTypeRepository(session)
        self.terrain_repository = TerrainRepository(session)
        self.repository = VehicleTypeTerrainPermissionRepository(session)

    def _validate_vehicle_type(self, vehicle_type_id: int) -> None:
        if self.vehicle_type_repository.get(vehicle_type_id) is None:
            raise NotFoundError("车辆类型不存在")

    def list(self, vehicle_type_id: int) -> list[VehicleTypeTerrainPermission]:
        self._validate_vehicle_type(vehicle_type_id)
        return self.repository.list_by_vehicle_type(vehicle_type_id)

    def add(
        self, vehicle_type_id: int, terrain_id: int
    ) -> VehicleTypeTerrainPermission:
        self._validate_vehicle_type(vehicle_type_id)
        if self.terrain_repository.get(terrain_id) is None:
            raise NotFoundError("地形不存在")
        if self.repository.get_permission(vehicle_type_id, terrain_id):
            raise ConflictError("该车辆类型已配置此地形通行权限")
        permission = VehicleTypeTerrainPermission(
            vehicle_type_id=vehicle_type_id, terrain_id=terrain_id
        )
        return self._commit(
            lambda: self.repository.add(permission), "地形通行权限重复"
        )

    def remove(self, vehicle_type_id: int, terrain_id: int) -> None:
        self._validate_vehicle_type(vehicle_type_id)
        permission = self.repository.get_permission(vehicle_type_id, terrain_id)
        if permission is None:
            raise NotFoundError("地形通行权限不存在")
        self._commit(
            lambda: self.repository.delete(permission), "无法删除地形通行权限"
        )
