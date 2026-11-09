from pathlib import Path

from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth_dependencies import CurrentUser, require_admin
from app.api.dependencies import DbSession
from app.api.driver.router import router as driver_router
from app.api.exception_handlers import register_exception_handlers
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.observability import install_telemetry
from app.services.delivery_proof_service import DeliveryProofService

settings = get_settings()

app = FastAPI(title=settings.app_name,
              docs_url="/docs" if settings.api_docs_enabled else None,
              redoc_url="/redoc" if settings.api_docs_enabled else None,
              openapi_url="/openapi.json" if settings.api_docs_enabled else None)
register_exception_handlers(app)
install_telemetry(app)
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

@app.get('/health/ready',tags=['system'])
def readiness(db: DbSession):
    try:
        db.execute(text('SELECT 1'))
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503,content={'status':'not_ready','database':'unavailable'})
    if settings.app_environment == 'production':
        try:
            expected = set(ScriptDirectory(str(Path(__file__).resolve().parents[1] / 'alembic')).get_heads())
            actual = set(db.execute(text('SELECT version_num FROM alembic_version')).scalars())
        except (SQLAlchemyError, CommandError, OSError):
            db.rollback()
            return JSONResponse(status_code=503, content={'status':'not_ready','database':'available','schema':'unavailable'})
        if actual != expected:
            return JSONResponse(status_code=503, content={'status':'not_ready', 'database':'available', 'schema':'mismatch'})
    return {'status':'ready','database':'available'}


@app.get('/health/agent', tags=['system'])
def agent_readiness():
    """Configuration readiness never implies a successful paid model call."""
    import importlib.util
    configured = bool(settings.agent_provider and settings.agent_model and settings.agent_api_key)
    dependencies = {name: importlib.util.find_spec(name) is not None
                    for name in ('langchain', 'langgraph', 'chromadb')}
    ready = configured and all(dependencies.values())
    return JSONResponse(status_code=200 if ready else 503, content={
        'status': 'configured' if ready else 'not_ready',
        'model_configured': configured, 'model_call': 'NOT_RUN',
        'dependencies': dependencies, 'graph_execution': 'NOT_RUN',
        'mcp_connection': 'NOT_RUN', 'rag_retrieval': 'NOT_RUN',
        'memory_enabled': settings.agent_memory_enabled,
        'langsmith_enabled': settings.langsmith_tracing})


@app.get('/api/v1/system/metrics', dependencies=[Depends(require_admin)], include_in_schema=False)
def http_metrics(request: Request):
    return request.app.state.http_metrics.snapshot()
