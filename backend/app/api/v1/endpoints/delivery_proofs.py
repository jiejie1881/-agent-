from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.auth_dependencies import CurrentUser, require_admin
from app.api.dependencies import DbSession
from app.schemas.driver import DeliveryProofResponse, DeliveryProofReviewRequest
from app.services.delivery_proof_service import DeliveryProofService

router = APIRouter(prefix="/delivery-proofs", tags=["delivery-proofs"])


@router.get("/{proof_id}/image")
def image(proof_id: int, db: DbSession, actor: CurrentUser):
    path, content_type = DeliveryProofService(db).image(actor, proof_id=proof_id)
    return FileResponse(path, media_type=content_type, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/{proof_id}/review", response_model=DeliveryProofResponse, dependencies=[Depends(require_admin)])
def review(proof_id: int, data: DeliveryProofReviewRequest, db: DbSession, actor: CurrentUser):
    return DeliveryProofResponse.model_validate(DeliveryProofService(db).review(proof_id, data, actor), from_attributes=True)
