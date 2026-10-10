from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.enums import UserRole
from app.domain.exceptions import ConflictError, NotFoundError
from app.models.vehicle import (
    Vehicle, VehicleType, VehicleTypeCargoCapability,
    VehicleTypeTerrainPermission,
)
from app.repositories.cargo_category_repository import CargoCategoryRepository
from app.repositories.terrain_repository import TerrainRepository
from app.repositories.user_repository import UserRepository
from app.repositories.vehicle_repository import (
    VehicleRepository,
    VehicleTypeRepository,
    VehicleTypeTerrainPermissionRepository,
    VehicleTypeCargoCapabilityRepository,
)
from app.schemas.vehicle import (
    VehicleCreate,
    VehicleTypeCreate,
    VehicleTypeUpdate,
    VehicleTypeCargoCapabilityReplace,
    VehicleUpdate,
)
from app.services.base import BaseService
from app.models.user import User
from app.services.audit_log_service import AuditLogService


class VehicleTypeService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = VehicleTypeRepository(session)
        self.cargo_category_repository = CargoCategoryRepository(session)

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
        def action() -> VehicleType:
            created = self.repository.add(vehicle_type)
            normal = self.cargo_category_repository.get_by_code("NORMAL")
            if normal is not None:
                self.session.add(
                    VehicleTypeCargoCapability(
                        vehicle_type_id=created.id,
                        cargo_category_id=normal.id,
                        is_allowed=True,
                    )
                )
                self.session.flush()
            return created
        return self._commit(action, "车辆类型编码或名称已存在")

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
        self.user_repository = UserRepository(session)

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

    def _validate_driver(self, driver_user_id: int | None) -> None:
        if driver_user_id is None:
            return
        driver = self.user_repository.get(driver_user_id)
        if driver is None:
            raise NotFoundError("司机账号不存在")
        if driver.role != UserRole.DRIVER:
            raise ConflictError("车辆只能绑定DRIVER角色账号")
        if not driver.is_active:
            raise ConflictError("不能绑定已停用的司机账号")

    def create(self, data: VehicleCreate, actor: User | None = None) -> Vehicle:
        self._validate_vehicle_type(data.vehicle_type_id)
        self._validate_driver(data.driver_user_id)
        if self.repository.get_by_code(data.code):
            raise ConflictError("车辆编码已存在")
        if self.repository.get_by_plate_number(data.plate_number):
            raise ConflictError("车牌号已存在")
        vehicle = Vehicle(**data.model_dump())
        def action():
            self.repository.add(vehicle)
            if actor and data.driver_user_id:
                AuditLogService(self.session).add(actor, "DRIVER_DEFAULT_VEHICLE_CHANGED", "Vehicle", vehicle.id, {"before_driver_id": None, "after_driver_id": data.driver_user_id})
            return vehicle
        return self._commit(action, "车辆编码或车牌号已存在")

    def update(self, vehicle_id: int, data: VehicleUpdate, actor: User | None = None) -> Vehicle:
        vehicle = self.get(vehicle_id)
        updates = data.model_dump(exclude_unset=True)
        before_driver_id = vehicle.driver_user_id
        if "vehicle_type_id" in updates:
            self._validate_vehicle_type(updates["vehicle_type_id"])
        if "driver_user_id" in updates:
            self._validate_driver(updates["driver_user_id"])
        for field, value in updates.items():
            setattr(vehicle, field, value)
        def action():
            self.repository.add(vehicle)
            if actor and "driver_user_id" in updates and before_driver_id != vehicle.driver_user_id:
                AuditLogService(self.session).add(actor, "DRIVER_DEFAULT_VEHICLE_CHANGED", "Vehicle", vehicle.id, {"before_driver_id": before_driver_id, "after_driver_id": vehicle.driver_user_id})
            return vehicle
        return self._commit(action, "车辆编码或车牌号已存在")

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


class VehicleTypeCargoCapabilityService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.vehicle_type_repository = VehicleTypeRepository(session)
        self.category_repository = CargoCategoryRepository(session)
        self.repository = VehicleTypeCargoCapabilityRepository(session)

    def _validate_vehicle_type(self, vehicle_type_id: int) -> None:
        if self.vehicle_type_repository.get(vehicle_type_id) is None:
            raise NotFoundError("车辆类型不存在")

    def list(self, vehicle_type_id: int) -> list[VehicleTypeCargoCapability]:
        self._validate_vehicle_type(vehicle_type_id)
        return self.repository.list_by_vehicle_type(vehicle_type_id)

    def replace(
        self, vehicle_type_id: int, data: VehicleTypeCargoCapabilityReplace
    ) -> list[VehicleTypeCargoCapability]:
        self._validate_vehicle_type(vehicle_type_id)
        capabilities: list[VehicleTypeCargoCapability] = []
        for item in data.capabilities:
            category = self.category_repository.get(item.cargo_category_id)
            if category is None:
                raise NotFoundError("货物分类不存在")
            if not category.is_active and item.is_allowed:
                raise ConflictError(f"货物分类 {category.name} 已停用")
            capabilities.append(
                VehicleTypeCargoCapability(
                    vehicle_type_id=vehicle_type_id,
                    **item.model_dump(),
                )
            )
        return self._commit(
            lambda: self.repository.replace(vehicle_type_id, capabilities),
            "车型运输能力配置重复或无效",
        )
