from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.vehicle import Vehicle
from app.models.vehicle_attendance import VehicleAttendance
from app.repositories.base import BaseRepository


class VehicleAttendanceRepository(BaseRepository[VehicleAttendance]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, VehicleAttendance)

    def get(self, entity_id: int) -> VehicleAttendance | None:
        statement = (
            select(VehicleAttendance)
            .options(
                joinedload(VehicleAttendance.vehicle).joinedload(Vehicle.vehicle_type)
            )
            .where(VehicleAttendance.id == entity_id)
        )
        return self.session.scalar(statement)

    def list_filtered(
        self,
        attendance_date: date | None,
        vehicle_id: int | None,
        offset: int,
        limit: int,
    ) -> list[VehicleAttendance]:
        statement = select(VehicleAttendance).options(
            joinedload(VehicleAttendance.vehicle).joinedload(Vehicle.vehicle_type)
        )
        if attendance_date is not None:
            statement = statement.where(VehicleAttendance.date == attendance_date)
        if vehicle_id is not None:
            statement = statement.where(VehicleAttendance.vehicle_id == vehicle_id)
        statement = statement.order_by(
            VehicleAttendance.date.desc(), VehicleAttendance.id
        ).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def get_by_date_vehicle(
        self, attendance_date: date, vehicle_id: int
    ) -> VehicleAttendance | None:
        statement = select(VehicleAttendance).where(
            VehicleAttendance.date == attendance_date,
            VehicleAttendance.vehicle_id == vehicle_id,
        )
        return self.session.scalar(statement)
