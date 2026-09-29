from fastapi import APIRouter, Depends, Query

from app.api.auth_dependencies import require_admin
from app.api.dependencies import DbSession
from app.schemas.audit_log import AuditLogResponse
from app.services.audit_log_service import AuditLogService

router = APIRouter(
    prefix="/audit-logs",
    tags=["audit-logs"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[AuditLogResponse])
def list_audit_logs(
    db: DbSession,
    action: str | None = Query(default=None, max_length=50),
    object_type: str | None = Query(default=None, max_length=50),
    user_id: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
):
    return AuditLogService(db).list(
        action, object_type, user_id, offset, limit
    )
