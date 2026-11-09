from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, TimeoutError as DatabasePoolTimeout

from app.domain.exceptions import (
    BusinessError,
    DispatchAdjustmentValidationError,
    DispatchPlanValidationError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DBAPIError)
    async def database_failure(request: Request, exc: DBAPIError):
        if getattr(exc.orig,'args',[None])[0] in (1205,1213):
            return JSONResponse(status_code=409,content={'detail':'数据库资源正在被其他操作修改，请刷新结果后重试','code':'DATABASE_CONFLICT'})
        return JSONResponse(status_code=503,content={'detail':'数据库暂不可用，请稍后重试并核对保存结果','code':'DATABASE_UNAVAILABLE'})

    @app.exception_handler(DatabasePoolTimeout)
    async def database_pool_timeout(request: Request, exc: DatabasePoolTimeout):
        return JSONResponse(status_code=503,content={'detail':'服务繁忙，请稍后重试并核对保存结果','code':'DATABASE_BUSY'})
    @app.exception_handler(DispatchAdjustmentValidationError)
    async def handle_dispatch_adjustment_validation_error(
        request: Request, exc: DispatchAdjustmentValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.message,
                "code": exc.code,
                "issues": exc.issues,
            },
        )

    @app.exception_handler(DispatchPlanValidationError)
    async def handle_dispatch_plan_validation_error(
        request: Request, exc: DispatchPlanValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.message,
                "code": exc.code,
                "issues": exc.issues,
            },
        )

    @app.exception_handler(BusinessError)
    async def handle_business_error(
        request: Request, exc: BusinessError
    ) -> JSONResponse:
        content = {"detail": exc.message}
        if exc.code is not None:
            content["code"] = exc.code
        return JSONResponse(status_code=exc.status_code, content=content)
