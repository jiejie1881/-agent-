from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.schemas.dispatch_validation import (
    DispatchValidationRequest,
    DispatchValidationResponse,
)
from app.services.dispatch_validation_service import DispatchValidationService

router = APIRouter(prefix="/dispatch-validations", tags=["dispatch-validations"])


@router.post("", response_model=DispatchValidationResponse)
def validate_dispatch(data: DispatchValidationRequest, db: DbSession):
    return DispatchValidationService(db).validate_dispatch(data)

