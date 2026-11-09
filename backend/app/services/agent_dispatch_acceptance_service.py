"""Turn a signed, freshly revalidated Agent candidate into one atomic DRAFT."""
import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.dispatch_engine.models import DispatchEngineResult, LoadedDemand, TripPlan, UnassignedDemand
from app.domain.enums import DeliveryDemandStatus, DispatchPlanStatus, UserRole
from app.domain.exceptions import BusinessError, ConflictError, PermissionDeniedError
from app.models.agent_dispatch_acceptance import AgentDispatchOperation, AgentDispatchPlanSource
from app.models.user import User
from app.models.dispatch_plan import DispatchOrder, DispatchPlan
from app.repositories.dispatch_engine_repository import DispatchEngineRepository
from app.repositories.dispatch_plan_repository import DispatchPlanRepository
from app.schemas.dispatch_candidate import DispatchCandidate, POLICY_VERSION
from app.services.agent_dispatch_receipt import candidate_digest, verify_receipt
from app.services.audit_log_service import AuditAction, AuditLogService
from app.services.delivery_demand_status_service import DeliveryDemandStatusService
from app.services.dispatch_candidate_validation_service import DispatchCandidateValidator
from app.services.dispatch_context_service import DispatchContextService
from app.services.dispatch_date_guard_service import lock_dispatch_date
from app.services.driver_leave_service import DriverLeaveService
from app.services.driver_scheduling_service import DriverSchedulingService


def candidate_to_result(candidate: DispatchCandidate, context, engine_input) -> DispatchEngineResult:
    """Map only server-owned quantities and resources after deterministic validation."""
    demands = {d.id: d for d in engine_input.demands}
    vehicles = {v.id: v for v in engine_input.vehicles}
    routes = engine_input.routes
    trips = []
    for item in candidate.trips:
        demand_rows = tuple(LoadedDemand(demands[d], demands[d].quantity) for d in item.demand_ids)
        trips.append(TripPlan(vehicle=vehicles[item.vehicle_id], period=item.period,
                              trip_no=item.trip_no, route=routes[item.route_id],
                              demands=demand_rows,
                              total_load=sum((d.quantity for d in demand_rows), start=0)))
    unassigned = tuple(UnassignedDemand(demands[item.demand_id], (item.explanation,))
                       for item in candidate.unassigned)
    return DispatchEngineResult(candidate.delivery_date, tuple(trips), unassigned)


class AgentDispatchAcceptanceService:
    def __init__(self, engine, settings: Settings):
        self.engine = engine
        self.settings = settings

    def accept(self, candidate: DispatchCandidate, receipt: str, idempotency_key: str,
               confirmed: bool, actor_id: int) -> dict:
        if not self.settings.agent_draft_accept_enabled or not (self.settings.agent_draft_accept_admin_enabled or self.settings.agent_draft_accept_dispatcher_enabled):
            raise PermissionDeniedError("Agent 草稿保存功能未启用")
        if self.engine.dialect.name != "mysql":
            raise BusinessError("Agent 草稿保存需要专用 MySQL 事务环境", 503, "MYSQL_REQUIRED")
        if not confirmed:
            raise BusinessError("请先明确确认保存草稿", 400, "CONFIRMATION_REQUIRED")
        if len(candidate.model_dump_json().encode("utf-8")) > 100_000:
            raise BusinessError("候选方案超过保存大小限制", 413, "CANDIDATE_TOO_LARGE")
        if not (8 <= len(idempotency_key) <= 100 and idempotency_key.isascii() and
                all(c.isalnum() or c in "-_" for c in idempotency_key)):
            raise BusinessError("幂等键格式无效", 400, "INVALID_IDEMPOTENCY_KEY")
        digest = hashlib.sha256((receipt + ":" + candidate_digest(candidate)).encode()).hexdigest()
        # Authentication used another Session; this transaction begins at SERIALIZABLE
        # before its first read. InnoDB range reads protect the reloaded snapshot.
        serial_engine = self.engine.execution_options(isolation_level="SERIALIZABLE")
        try:
            with Session(serial_engine, autoflush=False, expire_on_commit=False) as tx:
                with tx.begin():
                    actor = tx.get(User, actor_id, with_for_update=True)
                    if actor is None or not actor.is_active or not ((actor.role == UserRole.ADMIN and self.settings.agent_draft_accept_admin_enabled) or
                        (actor.role == UserRole.DISPATCHER and self.settings.agent_draft_accept_dispatcher_enabled)):
                        raise PermissionDeniedError()
                    existing = tx.scalar(select(AgentDispatchOperation).where(
                        AgentDispatchOperation.actor_id == actor.id,
                        AgentDispatchOperation.operation == "ACCEPT_DRAFT",
                        AgentDispatchOperation.idempotency_key == idempotency_key).with_for_update())
                    if existing is not None:
                        if existing.request_sha256 != digest:
                            raise ConflictError("幂等键已用于另一份候选")
                        plan = tx.get(DispatchPlan, existing.plan_id)
                        return self._response(plan)
                    proof = verify_receipt(receipt, candidate, actor, self.settings)
                    nonce_hash = hashlib.sha256(proof["nonce"].encode()).hexdigest()
                    if tx.scalar(select(AgentDispatchOperation.id).where(
                            AgentDispatchOperation.receipt_nonce_hash == nonce_hash)) is not None:
                        raise ConflictError("采纳凭据已使用")
                    # Preserve existing resource lock order, then serialize versions
                    # for this date. Traditional dispatch also takes resource locks.
                    DriverLeaveService(tx).lock_resources()
                    lock_dispatch_date(tx, candidate.delivery_date)
                    context = DispatchContextService(tx).load(candidate.delivery_date)
                    if context.snapshot_version != proof["snapshot_version"]:
                        raise BusinessError("业务快照已变化，请重新规划", 409, "STALE_CONTEXT")
                    if not any(d.schedulable for d in context.demands):
                        raise BusinessError("当前日期没有可保存的配送需求", 409, "NO_DEMANDS")
                    validation = DispatchCandidateValidator().validate(candidate, context, current_context=context)
                    if not validation.is_valid:
                        raise BusinessError("候选未通过当前业务规则校验", 409, "CANDIDATE_INVALID")
                    engine_input = DispatchEngineRepository(tx).load(candidate.delivery_date)
                    try:
                        result = candidate_to_result(candidate, context, engine_input)
                    except KeyError as exc:
                        raise BusinessError("候选资源在保存前已变化", 409, "STALE_CONTEXT") from exc
                    repository = DispatchPlanRepository(tx)
                    plan = repository.save_result(result, repository.next_version(candidate.delivery_date),
                                                  DispatchPlanStatus.DRAFT)
                    scheduling = DriverSchedulingService(tx)
                    saved_orders = list(tx.scalars(select(DispatchOrder).where(
                        DispatchOrder.plan_id == plan.id).order_by(DispatchOrder.id)))
                    for order, item in zip(saved_orders, candidate.trips, strict=True):
                        driver = scheduling.resolve(candidate.delivery_date, item.period.value, item.vehicle_id)
                        if driver.id != item.driver_id:
                            raise BusinessError("司机班次在保存前已变化", 409, "STALE_CONTEXT")
                        order.actual_driver_id = driver.id
                        order.driver_username_snapshot = driver.username
                        order.driver_name_snapshot = driver.display_name
                    assigned = {d for trip in candidate.trips for d in trip.demand_ids}
                    DeliveryDemandStatusService(tx).transition_many(
                        assigned, DeliveryDemandStatus.PLANNED,
                        allowed_current={DeliveryDemandStatus.PENDING, DeliveryDemandStatus.PLANNED})
                    tx.flush()
                    post_save = DispatchContextService(tx).load(candidate.delivery_date).snapshot_version
                    tx.add(AgentDispatchPlanSource(
                        plan_id=plan.id, receipt_nonce_hash=nonce_hash, run_id=proof["run_id"],
                        candidate_sha256=candidate_digest(candidate),
                        generated_snapshot_version=proof["snapshot_version"],
                        post_save_snapshot_version=post_save, policy_version=POLICY_VERSION,
                        accepted_by=actor.id, accepted_at=datetime.now(UTC)))
                    tx.add(AgentDispatchOperation(
                        actor_id=actor.id, operation="ACCEPT_DRAFT", idempotency_key=idempotency_key,
                        request_sha256=digest, receipt_nonce_hash=nonce_hash, plan_id=plan.id,
                        created_at=datetime.now(UTC)))
                    AuditLogService(tx).add(actor, AuditAction.AGENT_DRAFT_ACCEPTED, "DispatchPlan", plan.id,
                                            {"delivery_date": candidate.delivery_date.isoformat(),
                                             "version": plan.version, "run_id": proof["run_id"],
                                             "candidate_sha256": candidate_digest(candidate),
                                             "snapshot_version": proof["snapshot_version"]})
                    response = self._response(plan)
            return response
        except IntegrityError as exc:
            raise ConflictError("方案版本或采纳凭据发生并发冲突，请刷新后重试") from exc
        except DBAPIError as exc:
            if getattr(exc.orig, "args", [None])[0] in (1205, 1213):
                raise ConflictError("派车资源正在被其他操作修改，请刷新后重试") from exc
            raise

    @staticmethod
    def _response(plan) -> dict:
        return {"plan_id": plan.id, "delivery_date": plan.delivery_date,
                "version": plan.version, "status": plan.status.value}
