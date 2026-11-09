from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.domain.enums import VehicleTypeCode
from app.models.vehicle import (
    Vehicle,
    VehicleType,
    VehicleTypeTerrainPermission,
)
from app.repositories.base import BaseRepository


class VehicleTypeRepository(BaseRepository[VehicleType]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, VehicleType)

    def get_by_code(self, code: VehicleTypeCode) -> VehicleType | None:
        return self.session.scalar(select(VehicleType).where(VehicleType.code == code))

    def get_by_name(self, name: str) -> VehicleType | None:
        return self.session.scalar(select(VehicleType).where(VehicleType.name == name))

    def vehicle_count(self, vehicle_type_id: int) -> int:
        statement = select(func.count(Vehicle.id)).where(
            Vehicle.vehicle_type_id == vehicle_type_id
        )
        return self.session.scalar(statement) or 0


class VehicleRepository(BaseRepository[Vehicle]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Vehicle)

    def get(self, entity_id: int) -> Vehicle | None:
        statement = (
            select(Vehicle)
            .options(joinedload(Vehicle.vehicle_type))
            .where(Vehicle.id == entity_id)
        )
        return self.session.scalar(statement)

    def list(self, offset: int = 0, limit: int = 20) -> list[Vehicle]:
        statement = (
            select(Vehicle)
            .options(joinedload(Vehicle.vehicle_type))
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def get_by_code(self, code: str) -> Vehicle | None:
        return self.session.scalar(select(Vehicle).where(Vehicle.code == code))

    def get_by_plate_number(self, plate_number: str) -> Vehicle | None:
        return self.session.scalar(
            select(Vehicle).where(Vehicle.plate_number == plate_number)
        )

    def get_by_driver_user_id(self, driver_user_id: int) -> Vehicle | None:
        statement = (
            select(Vehicle)
            .options(joinedload(Vehicle.vehicle_type))
            .where(Vehicle.driver_user_id == driver_user_id)
        )
        return self.session.scalar(statement)


class VehicleTypeTerrainPermissionRepository(
    BaseRepository[VehicleTypeTerrainPermission]
):
    def __init__(self, session: Session) -> None:
        super().__init__(session, VehicleTypeTerrainPermission)

    def get_permission(
        self, vehicle_type_id: int, terrain_id: int
    ) -> VehicleTypeTerrainPermission | None:
        statement = select(VehicleTypeTerrainPermission).where(
            VehicleTypeTerrainPermission.vehicle_type_id == vehicle_type_id,
            VehicleTypeTerrainPermission.terrain_id == terrain_id,
        )
        return self.session.scalar(statement)

    def list_by_vehicle_type(
        self, vehicle_type_id: int
    ) -> list[VehicleTypeTerrainPermission]:
        statement = (
            select(VehicleTypeTerrainPermission)
            .options(joinedload(VehicleTypeTerrainPermission.terrain))
            .where(
                VehicleTypeTerrainPermission.vehicle_type_id == vehicle_type_id
            )
            .order_by(VehicleTypeTerrainPermission.id)
        )
        return list(self.session.scalars(statement))
