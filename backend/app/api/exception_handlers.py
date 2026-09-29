from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    BusinessError,
    DispatchAdjustmentValidationError,
    DispatchPlanValidationError,
)


def register_exception_handlers(app: FastAPI) -> None:
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
