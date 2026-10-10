from fastapi import FastAPI
from fastapi.responses import FileResponse
from app.api.auth_dependencies import CurrentUser
from app.api.dependencies import DbSession
from app.services.delivery_proof_service import DeliveryProofService

from app.api.exception_handlers import register_exception_handlers
from app.api.v1.router import api_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.driver.router import router as driver_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)
register_exception_handlers(app)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(driver_router)
@app.get("/uploads/delivery-proofs/{filename}", include_in_schema=False)
def legacy_proof_image(filename: str, db: DbSession, actor: CurrentUser):
    # Preserve stored URLs, but never expose receipt files through public StaticFiles.
    path, content_type = DeliveryProofService(db).image(actor, filename=filename)
    return FileResponse(path, media_type=content_type, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
