from fastapi import APIRouter, Depends
from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser, require_admin
from app.domain.exceptions import NotFoundError
from app.schemas.ai_demand import ParseDemandText, ConfirmDemandBatch
from app.schemas.dispatch_quality import CompareReports
from app.services.demand_text_parser_service import DemandTextParserService
from app.services.demand_batch_service import DemandBatchService
from app.services.dispatch_quality_service import DispatchQualityService
from app.services.quality_ai_summary_service import QualityAISummaryService

router = APIRouter(tags=['ai-demand-quality'])

@router.post('/delivery-demands/parse-text', dependencies=[Depends(require_admin)])
async def parse_text(data: ParseDemandText, db: DbSession):
    return await DemandTextParserService(db).parse(data.text)

@router.post('/delivery-demands/confirm-batch', dependencies=[Depends(require_admin)])
def confirm_batch(data: ConfirmDemandBatch, db: DbSession, actor: CurrentUser):
    return DemandBatchService(db).confirm(data, actor)

@router.post('/dispatch-plans/compare-quality')
def compare(data: CompareReports, db: DbSession):
    return DispatchQualityService(db).compare(data.report_ids)

@router.get('/dispatch-plans/{plan_id}/quality-report')
def latest(plan_id: int, db: DbSession):
    return DispatchQualityService(db).latest(plan_id)

@router.get('/dispatch-plans/{plan_id}/quality-reports')
def history(plan_id: int, db: DbSession):
    return DispatchQualityService(db).history(plan_id)

@router.post('/dispatch-plans/{plan_id}/quality-report')
def score(plan_id: int, db: DbSession, actor: CurrentUser):
    return DispatchQualityService(db).generate(plan_id, actor)

@router.post('/dispatch-plans/{plan_id}/quality-reports/{report_id}/ai-summary')
async def summary(plan_id: int, report_id: int, db: DbSession):
    row = DispatchQualityService(db).repository.report(report_id)
    if not row or row.plan_id != plan_id: raise NotFoundError('方案质量报告不存在')
    return await QualityAISummaryService().summarize(row.report)
