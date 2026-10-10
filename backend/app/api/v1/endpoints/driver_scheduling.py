from datetime import date

from fastapi import APIRouter, Depends

from app.api.auth_dependencies import CurrentUser, require_admin
from app.api.dependencies import DbSession
from app.schemas.auth import UserResponse
from app.schemas.driver_scheduling import (
    AttendanceInput, ScheduleInput, SubstituteInput, LeaveInput,
    DriverCreateInput, DriverUpdateInput, DriverPasswordInput,
    DefaultVehicleInput, ScheduleResponse, LeaveResponse, FixedAttendanceInput,
)
from app.services.driver_scheduling_service import DriverSchedulingService

router = APIRouter(prefix="/driver-management", tags=["driver-management"])


@router.get("/workbench")
def workbench(db: DbSession, day: date):
    return DriverSchedulingService(db).workbench(day)


@router.get("/drivers")
def drivers(db: DbSession, day: date):
    return DriverSchedulingService(db).list_drivers(day)


@router.post("/drivers", response_model=UserResponse, dependencies=[Depends(require_admin)])
def create_driver(data: DriverCreateInput, actor: CurrentUser, db: DbSession):
    return DriverSchedulingService(db).create_driver(data, actor)


@router.patch("/drivers/{driver_id}", response_model=UserResponse, dependencies=[Depends(require_admin)])
def update_driver(driver_id: int, data: DriverUpdateInput, actor: CurrentUser, db: DbSession):
    return DriverSchedulingService(db).update_driver(driver_id, data, actor)


@router.post("/drivers/{driver_id}/password", dependencies=[Depends(require_admin)])
def reset_password(driver_id: int, data: DriverPasswordInput, actor: CurrentUser, db: DbSession):
    DriverSchedulingService(db).reset_password(driver_id, data.password, actor)
    return {"updated": True}


@router.put("/drivers/{driver_id}/default-vehicle", dependencies=[Depends(require_admin)])
def default_vehicle(driver_id: int, data: DefaultVehicleInput, actor: CurrentUser, db: DbSession):
    return DriverSchedulingService(db).bind_default(driver_id, data.vehicle_id, actor)


@router.put("/attendances")
def attendance(data: AttendanceInput, actor: CurrentUser, db: DbSession):
    row = DriverSchedulingService(db).set_attendance(data, actor)
    return {"id": row.id, "available": row.available}


@router.put("/drivers/{driver_id}/fixed-attendance")
def fixed_attendance(driver_id: int, data: FixedAttendanceInput, actor: CurrentUser, db: DbSession):
    row = DriverSchedulingService(db).set_fixed_attendance(driver_id, data, actor)
    return {"id": row.id, "period": row.period, "available": row.available, "effective_date": row.effective_date}


@router.get("/schedules", response_model=list[ScheduleResponse])
def schedules(db: DbSession, day: date | None = None, driver_id: int | None = None):
    return DriverSchedulingService(db).list_schedules(day, driver_id)


@router.post("/schedules", response_model=ScheduleResponse)
def assign(data: ScheduleInput, actor: CurrentUser, db: DbSession):
    return DriverSchedulingService(db).assign(data, actor)


@router.get("/schedules/{schedule_id}/candidates")
def candidates(schedule_id: int, db: DbSession):
    return DriverSchedulingService(db).candidates(schedule_id)


@router.post("/schedules/{schedule_id}/substitute", response_model=ScheduleResponse, dependencies=[Depends(require_admin)])
def substitute(schedule_id: int, data: SubstituteInput, actor: CurrentUser, db: DbSession):
    return DriverSchedulingService(db).substitute(schedule_id, data.driver_id, actor)


@router.get("/leaves")
def leaves(db: DbSession, actor: CurrentUser):
    from app.services.driver_leave_service import DriverLeaveService
    service = DriverLeaveService(db)
    return [service.serialize(row, actor) for row in service.repository.leaves()]


@router.post("/leaves", response_model=LeaveResponse, dependencies=[Depends(require_admin)])
def create_leave(data: LeaveInput, actor: CurrentUser, db: DbSession):
    return DriverSchedulingService(db).create_leave(data, actor)


@router.post("/leaves/{leave_id}/cancel", response_model=LeaveResponse)
def cancel_leave(leave_id: int, actor: CurrentUser, db: DbSession):
    return DriverSchedulingService(db).cancel_leave(leave_id, actor)
