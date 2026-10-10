from datetime import date

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.api.auth_dependencies import DriverUser, require_driver
from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.driver import (
    DeliveryProofResponse,
    DeliveryStopFailRequest,
    DeliveryStopSignRequest,
    DriverProfileResponse,
    DriverTaskDetailResponse,
    DriverTaskPageResponse,
    DriverTaskStopResponse,
    DriverTaskSummaryResponse,
)
from app.services.auth_service import AuthService
from app.services.driver_service import DriverService

router = APIRouter(prefix="/api/driver", tags=["driver"])


@router.post("/auth/login", response_model=TokenResponse)
def driver_login(data: LoginRequest, db: DbSession):
    return AuthService(db).login_driver(data.username, data.password)


tasks_router = APIRouter(dependencies=[Depends(require_driver)])

from app.schemas.driver_leave import LeaveRequestInput
from app.services.driver_leave_service import DriverLeaveService


@tasks_router.post("/leaves")
def submit_leave(data: LeaveRequestInput, current_user: DriverUser, db: DbSession):
    service = DriverLeaveService(db)
    return service.serialize(service.submit(data, current_user), current_user)


@tasks_router.get("/leaves")
def my_leaves(current_user: DriverUser, db: DbSession):
    service = DriverLeaveService(db)
    return [service.serialize(row, current_user) for row in service.repository.leaves(current_user.id)]


@tasks_router.post("/leaves/{leave_id}/withdraw")
def withdraw_leave(leave_id: int, current_user: DriverUser, db: DbSession):
    service = DriverLeaveService(db)
    return service.serialize(service.withdraw(leave_id, current_user), current_user)


@tasks_router.get("/profile", response_model=DriverProfileResponse)
def get_driver_profile(current_user: DriverUser, db: DbSession):
    return DriverService(db).profile(current_user)


@tasks_router.get("/tasks/today", response_model=list[DriverTaskSummaryResponse])
def list_today_tasks(current_user: DriverUser, db: DbSession):
    return DriverService(db).today(current_user)


@tasks_router.get("/tasks/history", response_model=DriverTaskPageResponse)
def list_task_history(
    current_user: DriverUser,
    db: DbSession,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return DriverService(db).history(
        current_user,
        date_from=start_date,
        date_to=end_date,
        page=page,
        page_size=page_size,
    )


@tasks_router.get("/tasks/{task_id}", response_model=DriverTaskDetailResponse)
def get_driver_task(task_id: int, current_user: DriverUser, db: DbSession):
    return DriverService(db).get_task(task_id, current_user)


@tasks_router.post("/tasks/{task_id}/start", response_model=DriverTaskDetailResponse)
def start_driver_task(task_id: int, current_user: DriverUser, db: DbSession):
    return DriverService(db).start(task_id, current_user)


@tasks_router.post(
    "/tasks/{task_id}/complete", response_model=DriverTaskDetailResponse
)
def complete_driver_task(task_id: int, current_user: DriverUser, db: DbSession):
    return DriverService(db).complete(task_id, current_user)


@tasks_router.get(
    "/tasks/{task_id}/stops/{stop_id}", response_model=DriverTaskStopResponse
)
def get_driver_stop(
    task_id: int, stop_id: int, current_user: DriverUser, db: DbSession
):
    return DriverService(db).get_stop(task_id, stop_id, current_user)


@tasks_router.post(
    "/tasks/{task_id}/stops/{stop_id}/arrive",
    response_model=DriverTaskStopResponse,
)
def arrive_driver_stop(
    task_id: int, stop_id: int, current_user: DriverUser, db: DbSession
):
    return DriverService(db).arrive_stop(task_id, stop_id, current_user)


@tasks_router.post(
    "/tasks/{task_id}/stops/{stop_id}/sign",
    response_model=DriverTaskStopResponse,
)
def sign_driver_stop(
    task_id: int,
    stop_id: int,
    data: DeliveryStopSignRequest,
    current_user: DriverUser,
    db: DbSession,
):
    return DriverService(db).sign_stop(task_id, stop_id, data, current_user)


@tasks_router.post(
    "/tasks/{task_id}/stops/{stop_id}/fail",
    response_model=DriverTaskStopResponse,
)
def fail_driver_stop(
    task_id: int,
    stop_id: int,
    data: DeliveryStopFailRequest,
    current_user: DriverUser,
    db: DbSession,
):
    return DriverService(db).fail_stop(task_id, stop_id, data, current_user)


@tasks_router.post(
    "/tasks/{task_id}/stops/{stop_id}/proofs",
    response_model=DeliveryProofResponse,
)
async def upload_driver_stop_proof(
    task_id: int,
    stop_id: int,
    current_user: DriverUser,
    db: DbSession,
    file: UploadFile = File(...),
):
    max_bytes = get_settings().delivery_proof_max_bytes
    content = await file.read(max_bytes + 1)
    return DriverService(db).upload_proof(
        task_id,
        stop_id,
        file.content_type or "",
        content,
        current_user,
    )


router.include_router(tasks_router)
