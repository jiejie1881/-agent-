from datetime import date
from fastapi import APIRouter, Depends
from app.api.auth_dependencies import CurrentUser, require_admin
from app.api.dependencies import DbSession
from app.schemas.driver_leave import LeaveReviewInput, SubstitutionInput
from app.schemas.driver_scheduling import Shift
from app.services.driver_leave_service import DriverLeaveService
from app.services.driver_scheduling_service import DriverSchedulingService
from app.services.driver_substitution_recommendation_service import DriverSubstitutionRecommendationService

router = APIRouter(prefix="/driver-management", tags=["driver-leave-approval"])


@router.get("/leave-requests")
def requests(db: DbSession, actor: CurrentUser):
    service = DriverLeaveService(db)
    return [service.serialize(row, actor) for row in service.repository.leaves()]


@router.get("/leave-requests/{leave_id}")
def detail(leave_id: int, db: DbSession, actor: CurrentUser):
    service = DriverLeaveService(db)
    row = service.row(leave_id)
    return {**service.serialize(row, actor), "affected_tasks": service.affected(row)}


@router.post("/leave-requests/{leave_id}/review", dependencies=[Depends(require_admin)])
def review(leave_id: int, data: LeaveReviewInput, db: DbSession, actor: CurrentUser):
    service = DriverLeaveService(db)
    return service.serialize(service.review(leave_id, data, actor), actor)


@router.get("/substitution-candidates")
def candidates(db: DbSession, day: date, period: Shift, vehicle_id: int):
    return DriverSubstitutionRecommendationService(db).recommend(day, period, vehicle_id)


@router.get("/substitutions")
def substitutions(db: DbSession):
    service = DriverLeaveService(db)
    drivers = {d.id: d.display_name or d.username for d in service.scheduling.repository.drivers()}
    vehicles = {v.id: v.plate_number for v in service.scheduling.repository.vehicles()}
    return [{"id": row.id, "leave_request_id": row.leave_request_id, "vehicle_id": row.vehicle_id,
             "plate_number": vehicles.get(row.vehicle_id), "original_driver_id": row.original_driver_id,
             "original_driver_name": drivers.get(row.original_driver_id), "substitute_driver_id": row.substitute_driver_id,
             "substitute_driver_name": drivers.get(row.substitute_driver_id), "date": row.date, "period": row.period,
             "status": row.status, "confirmed_by": row.confirmed_by, "confirmed_at": row.confirmed_at,
             "created_at": row.created_at, "updated_at": row.updated_at} for row in service.repository.substitutions()]


@router.post("/substitutions", dependencies=[Depends(require_admin)])
def propose(data: SubstitutionInput, db: DbSession, actor: CurrentUser):
    return DriverLeaveService(db).propose(data, actor)


@router.post("/substitutions/{row_id}/confirm", dependencies=[Depends(require_admin)])
def confirm(row_id: int, db: DbSession, actor: CurrentUser):
    return DriverLeaveService(db).confirm(row_id, actor)


@router.post("/substitutions/{row_id}/cancel", dependencies=[Depends(require_admin)])
def cancel(row_id: int, db: DbSession, actor: CurrentUser):
    return DriverLeaveService(db).cancel_substitution(row_id, actor)


@router.get("/effective-drivers")
def effective(db: DbSession, day: date, period: Shift):
    service = DriverSchedulingService(db)
    return [{"vehicle_id": vehicle.id, "plate_number": vehicle.plate_number,
             **service.resolve_effective_driver(vehicle.id, day, period)} for vehicle in service.repository.vehicles()]
