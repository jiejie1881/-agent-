from datetime import date

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
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
def create_vehicle_attendance(data: VehicleAttendanceCreate, db: DbSession, actor: CurrentUser):
    return VehicleAttendanceService(db).with_audit(actor,'VEHICLE_ATTENDANCE_CREATED','VehicleAttendance',changes=data.model_dump()).create(data)


@router.patch("/{attendance_id}", response_model=VehicleAttendanceResponse)
def update_vehicle_attendance(
    attendance_id: int, data: VehicleAttendanceUpdate, db: DbSession, actor: CurrentUser
):
    return VehicleAttendanceService(db).with_audit(actor,'VEHICLE_ATTENDANCE_UPDATED','VehicleAttendance',attendance_id,data.model_dump(exclude_unset=True)).update(attendance_id, data)


@router.delete("/{attendance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle_attendance(attendance_id: int, db: DbSession, actor: CurrentUser) -> Response:
    VehicleAttendanceService(db).with_audit(actor,'VEHICLE_ATTENDANCE_DELETED','VehicleAttendance',attendance_id).delete(attendance_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

