from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.exception_handlers import register_exception_handlers
from app.api.v1.router import api_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.driver.router import router as driver_router
from app.core.config import get_settings
from app.core.storage import upload_root

settings = get_settings()

app = FastAPI(title=settings.app_name)
register_exception_handlers(app)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(driver_router)
app.mount(
    "/uploads",
    StaticFiles(directory=str(upload_root()), check_dir=False),
    name="uploads",
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
