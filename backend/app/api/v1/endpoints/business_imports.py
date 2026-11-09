from typing import Literal
from fastapi import APIRouter, File, UploadFile, Query, Response
from pydantic import BaseModel, Field
from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
from app.services.business_import_service import BusinessImportService, template, MAX_BYTES
from app.domain.exceptions import BusinessError

router = APIRouter(prefix="/business-imports", tags=["business-imports"])

class ConfirmImport(BaseModel):
    confirmed: bool = Field(default=False)

def view(batch):
    return {key: getattr(batch, key) for key in ("id", "kind", "status", "rows", "errors", "result_ids", "expires_at", "created_at", "updated_at")}

@router.get("/templates/{kind}")
def download_template(kind: str, format: Literal["csv", "xlsx"] = "csv", language: Literal["en", "zh"] = "en"):
    data = template(kind, format, language)
    return Response(data, media_type="text/csv" if format == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{kind}-template.{format}"'})

@router.get("")
def history(db: DbSession, actor: CurrentUser, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    return [view(batch) for batch in BusinessImportService(db).history(actor, offset, limit)]

@router.post("/{kind}/preview")
async def preview(kind: str, db: DbSession, actor: CurrentUser, file: UploadFile = File(...)):
    BusinessImportService.authorize(kind, actor)
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise BusinessError("文件不得超过 5MB", 422)
    return view(BusinessImportService(db).preview(kind, file.filename or "", data, actor))

@router.get("/{batch_id}")
def get_batch(batch_id: int, db: DbSession, actor: CurrentUser):
    return view(BusinessImportService(db).get(batch_id, actor))

@router.post("/{batch_id}/confirm")
def confirm(batch_id: int, data: ConfirmImport, db: DbSession, actor: CurrentUser):
    return view(BusinessImportService(db).confirm(batch_id, actor, data.confirmed))
