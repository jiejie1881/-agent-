from datetime import date

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession
from app.schemas.vehicle_attendance import (
    VehicleAttendanceCreate,
    VehicleAttendanceResponse,
    VehicleAttendanceUpdate,
)
from app.services.vehicle_attendance_service import VehicleAttendanceService

router = APIRouter(prefix="/vehicle-attendances", tags=["vehicle-attendances"])


@router.get("", response_model=list[VehicleAttendanceResponse])
def list_vehicle_attendances(
    db: DbSession,
    attendance_date: date | None = Query(default=None, alias="date"),
    vehicle_id: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    return VehicleAttendanceService(db).list(
        attendance_date, vehicle_id, offset, limit
    )


@router.get("/{attendance_id}", response_model=VehicleAttendanceResponse)
def get_vehicle_attendance(attendance_id: int, db: DbSession):
    return VehicleAttendanceService(db).get(attendance_id)


@router.post(
    "", response_model=VehicleAttendanceResponse, status_code=status.HTTP_201_CREATED
)
def create_vehicle_attendance(data: VehicleAttendanceCreate, db: DbSession):
    return VehicleAttendanceService(db).create(data)


@router.patch("/{attendance_id}", response_model=VehicleAttendanceResponse)
def update_vehicle_attendance(
    attendance_id: int, data: VehicleAttendanceUpdate, db: DbSession
):
    return VehicleAttendanceService(db).update(attendance_id, data)


@router.delete("/{attendance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle_attendance(attendance_id: int, db: DbSession) -> Response:
    VehicleAttendanceService(db).delete(attendance_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

