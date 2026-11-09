from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
from app.schemas.auto_dispatch import AutoDispatchRequest, AutoDispatchResponse
from app.services.auto_dispatch_service import AutoDispatchService

router = APIRouter(prefix="/auto-dispatch", tags=["auto-dispatch"])


@router.post("", response_model=AutoDispatchResponse)
def generate_dispatch_plan(
    data: AutoDispatchRequest, current_user: CurrentUser, db: DbSession
):
    return AutoDispatchService(db).dispatch(data, current_user)

