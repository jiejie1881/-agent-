from typing import Literal
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
from app.services.exception_case_service import ExceptionCaseService

router = APIRouter(prefix="/exception-cases", tags=["exception-cases"])
Category = Literal["FAILED_STOP", "MISSING_PROOF", "REJECTED_PROOF", "UNASSIGNED_DEMAND", "VEHICLE_UNAVAILABLE", "STATE_CONFLICT"]
class CreateCase(BaseModel):
    category: Category
    object_id: int = Field(gt=0)
    responsible_user_id: int | None = Field(None, gt=0)
class UpdateCase(BaseModel):
    revision: int = Field(gt=0)
    status: Literal["OPEN", "IN_PROGRESS", "RESOLVED"]
    responsible_user_id: int | None = Field(None, gt=0)
    note: str = Field(min_length=1, max_length=2000)
def view(item):
    return {key: getattr(item, key) for key in ("id", "source_key", "category", "reason", "status", "responsible_user_id", "resolution", "revision", "created_at", "updated_at")}
@router.get("")
def list_cases(db: DbSession, actor: CurrentUser, status: Literal["OPEN", "IN_PROGRESS", "RESOLVED"] | None = None,
    offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    return [view(item) for item in ExceptionCaseService(db).list(actor, status, offset, limit)]
@router.post("")
def create(data: CreateCase, db: DbSession, actor: CurrentUser):
    return view(ExceptionCaseService(db).create(data.category, data.object_id, data.responsible_user_id, actor))
@router.patch("/{case_id}")
def update(case_id: int, data: UpdateCase, db: DbSession, actor: CurrentUser):
    return view(ExceptionCaseService(db).update(case_id, data.revision, data.status, data.responsible_user_id, data.note, actor))
@router.get("/{case_id}/events")
def events(case_id: int, db: DbSession, actor: CurrentUser):
    return [{key: getattr(item, key) for key in ("id", "actor_id", "before_status", "after_status", "note", "created_at")}
        for item in ExceptionCaseService(db).events(case_id, actor)]
