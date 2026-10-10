import hashlib
import json
from datetime import datetime, timezone
from fastapi.encoders import jsonable_encoder
from app.core.config import get_settings
from app.domain.enums import DispatchPlanStatus
from app.domain.exceptions import ConflictError, NotFoundError
from app.models.ai_operations import DispatchQualityReport
from app.repositories.ai_operations_repository import AIOperationsRepository
from app.repositories.dispatch_plan_repository import DispatchPlanRepository
from app.services.dispatch_plan_publication_validator import DispatchPlanPublicationValidator
from app.services.dispatch_validation_service import DispatchValidationService
from app.services.dispatch_quality_metrics_service import DispatchQualityMetricsService
from app.services.dispatch_quality_engine import RULE_VERSION, score_quality
from app.services.audit_log_service import AuditLogService

SCOPE_FIELDS = ('id', 'date', 'store_id', 'period', 'quantity', 'priority')
def freeze_scope(demands):
    return sorted([jsonable_encoder({key: getattr(d, key) for key in SCOPE_FIELDS}) for d in demands], key=lambda d: d['id'])

def basis_hash(scope):
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

class DispatchQualityService:
    def __init__(self, session):
        self.session = session
        self.repository = AIOperationsRepository(session)
        self.plans = DispatchPlanRepository(session)

    def generate(self, plan_id, actor, scope=None, *, commit=True):
        plan = self.plans.get(plan_id)
        if not plan: raise NotFoundError('派车方案不存在')
        previous = self.repository.reports(plan_id)
        origin = 'FROZEN_INPUT'
        if scope is None:
            if previous: scope, origin = previous[0].scope, previous[0].report['basis_origin']
            else:
                represented = {d.delivery_demand_id for o in plan.orders for d in o.details} | {d.delivery_demand_id for d in plan.unassigned_demands}
                scope = freeze_scope(self.repository.demands(represented))
                origin = 'LEGACY_RECONSTRUCTED'
        # Ignore retired fields in old input snapshots without rewriting historical reports.
        scope = [{key: item[key] for key in SCOPE_FIELDS if key in item} for item in scope]
        # Report never changes demand/plan state; check current data, freeze the resulting facts.
        issues = DispatchPlanPublicationValidator(DispatchValidationService(self.session)).validate(plan, for_update=False)
        metrics, trips, unassigned, exceptions, traces, categorized, groups = DispatchQualityMetricsService(self.session).collect(plan, scope, issues)
        traces['audit'] = self.repository.audit_exists(plan_id)
        current = {d.id: d for d in self.repository.demands({x['id'] for x in scope})}
        critical = len(current) != len(scope) or any(x['date'] != plan.delivery_date.isoformat() for x in scope)
        changes = freeze_scope(current.values()) != scope
        if changes: critical = True
        from app.services.business_labels import quality_entities
        scored = score_quality(metrics, categorized, groups, traces, target=get_settings().quality_load_target, cancelled=plan.status == DispatchPlanStatus.CANCELLED, critical_missing=critical)
        report = jsonable_encoder({**scored, "plan_id": plan.id, "delivery_date": plan.delivery_date, "plan_version": plan.version, "plan_status_at_scoring": plan.status.value,
            "generated_at": datetime.now(timezone.utc), "basis_origin": origin, "basis_hash": basis_hash(scope), "metrics": metrics, "trips": trips,
            "issues": categorized, "unassigned": unassigned, "exceptions": exceptions, "trace_checks": traces,
            "entities": quality_entities(plan, current.values()),
            "publication_validation": 'FAIL' if issues or plan.status == DispatchPlanStatus.CANCELLED or not plan.orders else 'PASS',
            "notices": ['校验和异常是评分时刻的数据，不保证将来发布通过；发布必须再次正式校验。', '无独立异常工单状态，只评分可验证的原因记录和停靠点终态。'] + (['旧方案输入范围无法追溯，只重建其已记录范围，属于临时评分，不保证原始需求全量覆盖。'] if origin == 'LEGACY_RECONSTRUCTED' else [])})
        if origin == 'LEGACY_RECONSTRUCTED':
            report['coverage'] = None  # 原始输入范围未知，不能冒充完整覆盖率。
            if report['status'] == 'SCORED': report['status'] = 'PROVISIONAL'
        report['summary'] = self.template_summary(report)
        row = self.repository.add(DispatchQualityReport(plan_id=plan_id, rule_version=RULE_VERSION, basis_hash=report['basis_hash'], scope=scope, report=report))
        AuditLogService(self.session).add(actor, 'DISPATCH_QUALITY_SCORED', 'DispatchQualityReport', row.id, {"plan_id": plan_id, "rule_version": RULE_VERSION})
        if commit: self.session.commit()
        return self.serialize(row)

    @staticmethod
    def template_summary(report):
        m = report['metrics']
        entities = report.get('entities', {})
        tasks = {t['order_id']: t for t in entities.get('tasks', [])}
        labels = []
        for trip in report.get('trips', []):
            task = tasks.get(trip['order_id'])
            if task and trip['load_ratio'] < .5:
                v = task['vehicle']
                labels.append(f"复核车辆 {v['code']}（{v['plate_number']}）任务 {task['task_code']} 的低装载情况；任何合并或移动仍须正式校验。")
        for d in entities.get('demands', []):
            if any(u['demand_id'] == d['id'] for u in report.get('unassigned', [])):
                labels.append(f"人工核查 {d['store_name']} 的需求 {d['code']}，具体未分配原因见报告明细。")
        return {"mode": 'RULE_TEMPLATE', "text": f"方案V{report['plan_version']}：有效需求{m['valid_demand_count']}条，完整分配{m['assigned_demand_count']}条，未分配{m['unassigned_count']}条；使用{m['vehicle_count']}辆车、{m['trip_count']}趟。评分{report['total_score'] if report['total_score'] is not None else '无法评分'}，发布校验{report['publication_validation']}。",
            "suggestions": ['先处理发布校验问题，评分不能替代正式发布校验。' if report['issues'] else '发布时仍需重新检查车辆、司机和运输规则。'] + (["复核未分配原因与可用运力，任何调整必须由管理员确认。"] if m['unassigned_count'] else []) + labels}

    @staticmethod
    def serialize(row):
        return {"id": row.id, **row.report}

    def history(self, plan_id):
        if not self.plans.get(plan_id): raise NotFoundError('派车方案不存在')
        return [self.serialize(r) for r in self.repository.reports(plan_id)]

    def latest(self, plan_id):
        history = self.history(plan_id)
        return history[0] if history else None

    def compare(self, report_ids):
        rows = [self.repository.report(key) for key in report_ids]
        if any(r is None for r in rows): raise NotFoundError('质量报告不存在')
        reports = [self.serialize(r) for r in rows]
        if len({r['delivery_date'] for r in reports}) != 1: raise ConflictError('只能对比同一天的方案')
        comparable = len({(r['rule_version'], r['basis_hash'], r['utilization_target']) for r in reports}) == 1 and all(r['basis_origin'] == 'FROZEN_INPUT' and r['total_score'] is not None for r in reports)
        return {"comparable": comparable, "notice": '同一需求基准和规则，可直接对比' if comparable else '需求范围、评分规则、目标参数或历史基准不一致，不可直接比较分数', "reports": reports}
