from datetime import date

from sqlalchemy.orm import Session

from app.domain.exceptions import ConflictError, NotFoundError
from app.models.vehicle_attendance import VehicleAttendance
from app.repositories.vehicle_attendance_repository import VehicleAttendanceRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle_attendance import (
    VehicleAttendanceCreate,
    VehicleAttendanceUpdate,
)
from app.services.base import BaseService


class VehicleAttendanceService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = VehicleAttendanceRepository(session)
        self.vehicle_repository = VehicleRepository(session)

    def list(
        self,
        attendance_date: date | None,
        vehicle_id: int | None,
        offset: int,
        limit: int,
    ) -> list[VehicleAttendance]:
        return self.repository.list_filtered(
            attendance_date, vehicle_id, offset, limit
        )

    def get(self, attendance_id: int) -> VehicleAttendance:
        attendance = self.repository.get(attendance_id)
        if attendance is None:
            raise NotFoundError("车辆出勤记录不存在")
        return attendance

    def _validate_vehicle(self, vehicle_id: int) -> None:
        if self.vehicle_repository.get(vehicle_id) is None:
            raise NotFoundError("车辆不存在")

    def create(self, data: VehicleAttendanceCreate) -> VehicleAttendance:
        self._validate_vehicle(data.vehicle_id)
        if self.repository.get_by_date_vehicle(data.date, data.vehicle_id):
            raise ConflictError("该车辆当天已有出勤记录")
        attendance = VehicleAttendance(**data.model_dump())
        return self._commit(
            lambda: self.repository.add(attendance), "该车辆当天已有出勤记录"
        )

    def update(
        self, attendance_id: int, data: VehicleAttendanceUpdate
    ) -> VehicleAttendance:
        attendance = self.get(attendance_id)
        updates = data.model_dump(exclude_unset=True)
        vehicle_id = updates.get("vehicle_id", attendance.vehicle_id)
        attendance_date = updates.get("date", attendance.date)
        self._validate_vehicle(vehicle_id)
        duplicate = self.repository.get_by_date_vehicle(attendance_date, vehicle_id)
        if duplicate is not None and duplicate.id != attendance_id:
            raise ConflictError("该车辆当天已有出勤记录")
        for field, value in updates.items():
            setattr(attendance, field, value)
        return self._commit(
            lambda: self.repository.add(attendance), "该车辆当天已有出勤记录"
        )

    def delete(self, attendance_id: int) -> None:
        attendance = self.get(attendance_id)
        self._commit(
            lambda: self.repository.delete(attendance), "无法删除车辆出勤记录"
        )

