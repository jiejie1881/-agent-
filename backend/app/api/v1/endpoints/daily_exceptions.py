from datetime import date

from fastapi import APIRouter, Query

from app.api.dependencies import DbSession
from app.schemas.daily_exception import DailyExceptionReportResponse
from app.services.daily_exception_service import DailyExceptionService

router = APIRouter(prefix="/daily-exceptions", tags=["daily-exceptions"])


@router.get("", response_model=DailyExceptionReportResponse)
def get_daily_exception_report(
    db: DbSession,
    date: date = Query(...),
    plan_id: int | None = Query(default=None, gt=0),
    example_limit: int = Query(default=10, ge=1, le=20),
):
    return DailyExceptionService(db).report(date, plan_id, example_limit)
