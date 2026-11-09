from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select, update

from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryPeriod,
    UserRole,
    VehicleTypeCode,
)
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchOrder, DispatchOrderDetail, DispatchPlan
from app.models.driver_scheduling import (
    DriverAttendance,
    DriverLeave,
    DriverSchedule,
    DriverSubstitution,
)
from app.models.route import Route, RouteTerrainConfig
from app.models.store import Store, StoreRoute
from app.models.terrain import Terrain
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleType, VehicleTypeTerrainPermission
from app.models.vehicle_attendance import VehicleAttendance
from app.schemas.dispatch_candidate import DispatchCandidate
from app.services.dispatch_candidate_validation_service import (
    DispatchCandidateValidator,
)
from app.services.dispatch_context_service import DispatchContextService

DAY = date(2026, 11, 10)


@pytest.fixture
def resources(session):
    terrain = Terrain(code="T", name="普通")
    route = Route(code="R", name="线路")
    store = Store(code="S", name="门店")
    driver = User(username="foundation-driver", password_hash="test-only-unusable-hash", role=UserRole.DRIVER, is_active=True)
    standby = User(username="foundation-standby", password_hash="test-only-unusable-hash", role=UserRole.DRIVER, is_active=True)
    kind = VehicleType(code=VehicleTypeCode.SMALL_VAN, name="小包", min_load=100, max_load=500, is_active=True)
    session.add_all([terrain, route, store, driver, standby, kind])
    session.flush()
    vehicle = Vehicle(code="V", plate_number="湘A00001", vehicle_type_id=kind.id, driver_user_id=driver.id, is_active=True)
    session.add(vehicle)
    session.flush()
    demand = DeliveryDemand(date=DAY, store_id=store.id, period=DeliveryPeriod.MORNING,
                            quantity=200, status=DeliveryDemandStatus.PENDING)
    attendance = VehicleAttendance(date=DAY, vehicle_id=vehicle.id, available=True)
    session.add_all([demand, attendance,
        StoreRoute(store_id=store.id, route_id=route.id),
        RouteTerrainConfig(route_id=route.id, terrain_id=terrain.id, effective_date=DAY),
        VehicleTypeTerrainPermission(vehicle_type_id=kind.id, terrain_id=terrain.id),
        DriverAttendance(driver_id=driver.id, date=DAY, period="MORNING", available=True, actor_id=driver.id),
        DriverAttendance(driver_id=standby.id, date=DAY, period="MORNING", available=True, actor_id=driver.id)])
    session.commit()
    return {
        "terrain": terrain,
        "route": route,
        "store": store,
        "driver": driver,
        "standby": standby,
        "kind": kind,
        "vehicle": vehicle,
        "demand": demand,
        "attendance": attendance,
    }


def context(session):
    return DispatchContextService(session).load(DAY)


def candidate(ctx, r, **changes):
    data = {
        "candidate_id": "test-candidate",
        "delivery_date": DAY,
        "snapshot_version": ctx.snapshot_version,
        "trips": [{
            "vehicle_id": r["vehicle"].id,
            "driver_id": r["driver"].id,
            "route_id": r["route"].id,
            "period": "MORNING",
            "trip_no": 1,
            "demand_ids": [r["demand"].id],
        }],
    }
    data.update(changes)
    return data


def codes(result):
    return {v.violation_code for v in result.violations}


def test_step10b_receipt_binds_candidate_actor_and_expiry(session, resources):
    from datetime import datetime, UTC, timedelta
    from pydantic import SecretStr
    from app.core.config import get_settings
    from app.domain.exceptions import PermissionDeniedError
    from app.schemas.agent_dispatch import ShadowDispatchResult
    from app.services.agent_dispatch_receipt import issue_receipt, verify_receipt

    ctx = context(session)
    parsed = DispatchCandidate.model_validate(candidate(ctx, resources))
    validation = DispatchCandidateValidator().validate(parsed, ctx, current_context=ctx)
    result = ShadowDispatchResult(run_id="test-run", status="SUCCESS", reason_code="VALID_CANDIDATE",
                                  message="ok", snapshot_version=ctx.snapshot_version,
                                  freshness_checked=True, candidate=parsed, validation=validation)
    settings = get_settings().model_copy(update={
        "agent_draft_receipt_secret": SecretStr("test-only-agent-draft-secret-with-32-bytes"),
        "agent_draft_receipt_ttl_seconds": 60,
    })
    now = datetime(2026, 11, 10, tzinfo=UTC)
    receipt = issue_receipt(result, resources["driver"], settings, now=now)
    assert verify_receipt(receipt, parsed, resources["driver"], settings, now=now)["run_id"] == "test-run"
    tampered = parsed.model_copy(update={"planning_explanation": "altered"})
    with pytest.raises(PermissionDeniedError):
        verify_receipt(receipt, tampered, resources["driver"], settings, now=now)
    with pytest.raises(PermissionDeniedError):
        verify_receipt(receipt, parsed, resources["standby"], settings, now=now)
    with pytest.raises(PermissionDeniedError):
        verify_receipt(receipt, parsed, resources["driver"], settings, now=now + timedelta(seconds=61))
    with pytest.raises(PermissionDeniedError):
        verify_receipt(receipt, parsed, resources["driver"],
                       settings.model_copy(update={"agent_draft_receipt_key_version": 2}), now=now)


def test_step10b_server_owned_mapping_and_sqlite_write_guard(session, resources):
    from app.core.config import get_settings
    from app.domain.exceptions import BusinessError
    from app.repositories.dispatch_engine_repository import DispatchEngineRepository
    from app.services.agent_dispatch_acceptance_service import AgentDispatchAcceptanceService, candidate_to_result

    ctx = context(session)
    parsed = DispatchCandidate.model_validate(candidate(ctx, resources))
    result = candidate_to_result(parsed, ctx, DispatchEngineRepository(session).load(DAY))
    assert result.trips[0].total_load == Decimal("200.00")
    assert result.trips[0].demands[0].quantity == Decimal("200.00")
    settings = get_settings().model_copy(update={
        "agent_draft_accept_enabled": True, "agent_draft_accept_admin_enabled": True,
    })
    with pytest.raises(BusinessError) as error:
        AgentDispatchAcceptanceService(session.get_bind(), settings).accept(
            parsed, "not-a-receipt", "idempotency-key-123", True, resources["driver"].id)
    assert error.value.code == "MYSQL_REQUIRED"
    assert session.scalar(select(DispatchPlan.id)) is None


def test_step10b_agent_draft_cannot_use_traditional_publish_entry(session, resources):
    from datetime import UTC, datetime
    from app.domain.enums import DispatchPlanStatus
    from app.domain.exceptions import PermissionDeniedError
    from app.models.agent_dispatch_acceptance import AgentDispatchPlanSource
    from app.services.dispatch_plan_service import DispatchPlanService

    plan = DispatchPlan(delivery_date=DAY, version=1, status=DispatchPlanStatus.DRAFT)
    session.add(plan)
    session.flush()
    session.add(AgentDispatchPlanSource(
        plan_id=plan.id, receipt_nonce_hash="a" * 64, run_id="test-run",
        candidate_sha256="b" * 64, generated_snapshot_version="c" * 64,
        post_save_snapshot_version="d" * 64, policy_version="dispatch-context-v1",
        accepted_by=resources["driver"].id, accepted_at=datetime.now(UTC)))
    session.commit()
    with pytest.raises(PermissionDeniedError):
        DispatchPlanService(session).publish(plan.id, resources["driver"])
    session.expire_all()
    assert session.get(DispatchPlan, plan.id).status == DispatchPlanStatus.DRAFT


def test_step10c_preview_is_read_only_and_detects_changed_snapshot(session, resources):
    from datetime import UTC, datetime
    from app.domain.enums import DispatchPlanStatus
    from app.models.agent_dispatch_acceptance import AgentDispatchPlanSource
    from app.services.agent_publish_preview_service import AgentPublishPreviewService

    admin = User(username="preview-admin", password_hash="test-only", role=UserRole.ADMIN, is_active=True)
    plan = DispatchPlan(delivery_date=DAY, version=1, status=DispatchPlanStatus.DRAFT)
    session.add_all([admin, plan])
    session.commit()
    baseline = context(session).snapshot_version
    session.add(AgentDispatchPlanSource(
        plan_id=plan.id, receipt_nonce_hash="e" * 64, run_id="preview-run",
        candidate_sha256="f" * 64, generated_snapshot_version=baseline,
        post_save_snapshot_version=baseline, policy_version="dispatch-context-v1",
        accepted_by=admin.id, accepted_at=datetime.now(UTC)))
    session.commit()
    preview = AgentPublishPreviewService(session).preview(plan.id, admin)
    assert preview["stale"] is False and preview["can_confirm_publish"] is False
    assert session.get(DispatchPlan, plan.id).status == DispatchPlanStatus.DRAFT
    resources["demand"].quantity = Decimal("300.00")
    session.commit()
    assert AgentPublishPreviewService(session).preview(plan.id, admin)["stale"] is True


def test_step10c_publish_receipt_binds_plan_actor_snapshot_and_expiry(session, resources):
    from datetime import UTC, datetime, timedelta
    from pydantic import SecretStr
    from app.core.config import get_settings
    from app.domain.enums import DispatchPlanStatus
    from app.domain.exceptions import PermissionDeniedError
    from app.services.agent_publish_receipt import issue_publish_receipt, verify_publish_receipt

    admin = User(username="publish-admin", password_hash="test-only", role=UserRole.ADMIN, is_active=True)
    other = User(username="other-admin", password_hash="test-only", role=UserRole.ADMIN, is_active=True)
    plan = DispatchPlan(delivery_date=DAY, version=1, status=DispatchPlanStatus.DRAFT)
    session.add_all([admin, other, plan])
    session.commit()
    settings = get_settings().model_copy(update={
        "agent_draft_receipt_secret": SecretStr("test-only-agent-publish-secret-with-32-bytes"),
        "agent_publish_receipt_ttl_seconds": 60,
    })
    now = datetime(2026, 11, 10, tzinfo=UTC)
    token = issue_publish_receipt(plan, admin, "a" * 64, "b" * 64, settings, now=now)
    assert verify_publish_receipt(token, plan, admin, "a" * 64, "b" * 64, settings, now=now)["plan_id"] == plan.id
    for actor, snapshot, digest, timestamp in (
        (other, "a" * 64, "b" * 64, now),
        (admin, "c" * 64, "b" * 64, now),
        (admin, "a" * 64, "d" * 64, now),
        (admin, "a" * 64, "b" * 64, now + timedelta(seconds=61)),
    ):
        with pytest.raises(PermissionDeniedError):
            verify_publish_receipt(token, plan, actor, snapshot, digest, settings, now=timestamp)
    with pytest.raises(PermissionDeniedError):
        verify_publish_receipt(token[:-2] + "xx", plan, admin, "a" * 64, "b" * 64, settings, now=now)


def test_step10c_publish_requires_mysql_and_independent_admin_permission(session, monkeypatch):
    from app.core.config import get_settings
    from app.domain.exceptions import BusinessError
    from app.domain.permissions import Permission, has_permission
    from app.services.agent_publish_service import AgentPublishService

    disabled = get_settings().model_copy(update={
        "agent_plan_publish_enabled": False,
        "agent_plan_publish_admin_enabled": False,
    })
    monkeypatch.setattr("app.core.config.get_settings", lambda: disabled)
    assert not has_permission(UserRole.ADMIN, Permission.AGENT_PLAN_PUBLISH)
    enabled = disabled.model_copy(update={
        "agent_plan_publish_enabled": True,
        "agent_plan_publish_admin_enabled": True,
    })
    monkeypatch.setattr("app.core.config.get_settings", lambda: enabled)
    assert has_permission(UserRole.ADMIN, Permission.AGENT_PLAN_PUBLISH)
    assert not has_permission(UserRole.DISPATCHER, Permission.AGENT_PLAN_PUBLISH)
    with pytest.raises(BusinessError) as error:
        AgentPublishService(session.get_bind(), enabled).confirm(1, "token", "idempotency-key-123", True, 1)
    assert error.value.code == "MYSQL_REQUIRED"


def test_valid_snapshot_roundtrip_and_no_credentials(session, resources):
    ctx = context(session)
    assert ctx.snapshot_version == context(session).snapshot_version
    assert ctx.fingerprint() == ctx.snapshot_version
    assert ctx.daily_trip_limit is None and ctx.multiple_trips_per_period
    assert "password" not in ctx.model_dump_json() and "token" not in ctx.model_dump_json()
    parsed = DispatchCandidate.model_validate_json(DispatchCandidate.model_validate(candidate(ctx, resources)).model_dump_json())
    result = DispatchCandidateValidator().validate(parsed, ctx)
    assert result.is_valid and result.trip_loads == (Decimal("200.00"),)
    assert DispatchCandidate.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("quantity,code", [(600, "OVERLOAD"), (50, "BELOW_MIN_LOAD")])
def test_load_limits(session, resources, quantity, code):
    resources["demand"].quantity = quantity
    session.commit()
    ctx = context(session)
    assert code in codes(DispatchCandidateValidator().validate(candidate(ctx, resources), ctx))


def test_duplicate_demand_and_trip(session, resources):
    ctx = context(session)
    data = candidate(ctx, resources)
    data["trips"] *= 2
    assert {"DUPLICATE_DEMAND", "TRIP_CONFLICT"} <= codes(DispatchCandidateValidator().validate(data, ctx))


def test_multiple_trips_are_not_artificially_limited(session, resources):
    other = Store(code="S2", name="门店2")
    session.add(other); session.flush()
    session.add(StoreRoute(store_id=other.id, route_id=resources["route"].id))
    demand = DeliveryDemand(date=DAY, store_id=other.id, period=DeliveryPeriod.MORNING, quantity=200, status=DeliveryDemandStatus.PENDING)
    session.add(demand); session.commit()
    ctx = context(session)
    data = candidate(ctx, resources)
    data["trips"].append({**data["trips"][0], "trip_no": 2, "demand_ids": [demand.id]})
    assert DispatchCandidateValidator().validate(data, ctx).is_valid


def test_incompatible_route(session, resources):
    link = session.scalar(select(StoreRoute))
    session.delete(link); session.commit()
    ctx = context(session)
    assert "ROUTE_NOT_ALLOWED" in codes(DispatchCandidateValidator().validate(candidate(ctx, resources), ctx))


@pytest.mark.parametrize("status,code", [("PENDING", "DRIVER_LEAVE_PENDING_REVIEW"), ("APPROVED", "DRIVER_ON_LEAVE_NO_CONFIRMED_SUBSTITUTE")])
def test_leave_without_confirmed_cover(session, resources, status, code):
    session.add(DriverLeave(driver_id=resources["driver"].id, start_date=DAY, end_date=DAY,
                           period="MORNING", reason="测试", status=status, actor_id=resources["driver"].id))
    session.commit()
    ctx = context(session)
    assert code in codes(DispatchCandidateValidator().validate(candidate(ctx, resources), ctx))


def test_confirmed_substitute_is_valid(session, resources):
    a, b, v = resources["driver"], resources["standby"], resources["vehicle"]
    leave = DriverLeave(driver_id=a.id, start_date=DAY, end_date=DAY, period="MORNING", reason="测试", status="APPROVED", actor_id=a.id)
    session.add(leave); session.flush()
    session.add_all([
        DriverSchedule(date=DAY, period="MORNING", vehicle_id=v.id, driver_id=b.id, original_driver_id=a.id, kind="SUBSTITUTE", status="ACTIVE", actor_id=a.id),
        DriverSubstitution(leave_request_id=leave.id, date=DAY, period="MORNING", vehicle_id=v.id,
                           original_driver_id=a.id, substitute_driver_id=b.id, status="CONFIRMED", active_vehicle_id=v.id, active_driver_id=b.id)])
    session.commit()
    ctx = context(session)
    data = candidate(ctx, resources)
    data["trips"][0]["driver_id"] = b.id
    assert DispatchCandidateValidator().validate(data, ctx).is_valid
    data["trips"][0]["driver_id"] = a.id
    assert "DRIVER_ASSIGNMENT_MISMATCH" in codes(DispatchCandidateValidator().validate(data, ctx))


@pytest.mark.parametrize("target,field,value,code", [
    ("attendance", "available", False, "VEHICLE_UNAVAILABLE"),
    ("vehicle", "is_active", False, "VEHICLE_INACTIVE"),
    ("kind", "is_active", False, "VEHICLE_TYPE_INACTIVE"),
    ("driver", "is_active", False, "DRIVER_UNAVAILABLE"),
])
def test_inactive_resources(session, resources, target, field, value, code):
    setattr(resources[target], field, value); session.commit()
    ctx = context(session)
    assert code in codes(DispatchCandidateValidator().validate(candidate(ctx, resources), ctx))


def test_unassigned_is_valid_but_not_assigned(session, resources):
    ctx = context(session)
    result = DispatchCandidateValidator().validate(candidate(ctx, resources, trips=[],
        unassigned=[{"demand_id": resources["demand"].id, "explanation": "本次未找到组合"}]), ctx)
    assert result.is_valid and result.assigned_count == 0 and result.unassigned_count == 1
    assert "MISSING_DEMAND" in codes(DispatchCandidateValidator().validate(candidate(ctx, resources, trips=[]), ctx))


def test_empty_context(session):
    ctx = context(session)
    assert DispatchCandidateValidator().validate({
        "candidate_id": "empty",
        "delivery_date": DAY,
        "snapshot_version": ctx.snapshot_version,
    }, ctx).is_valid


@pytest.mark.parametrize("changes", [{"unexpected": True}, {"trips": [{"vehicle_id": 0}]}, {"candidate_id": " "}, {"snapshot_version": "bad"}])
def test_invalid_structure(session, resources, changes):
    ctx = context(session)
    assert "INVALID_CANDIDATE" in codes(DispatchCandidateValidator().validate(candidate(ctx, resources, **changes), ctx))


def test_mismatched_date_and_snapshot(session, resources):
    ctx = context(session)
    result = DispatchCandidateValidator().validate(candidate(ctx, resources, delivery_date="2026-11-11", snapshot_version="0" * 64), ctx)
    assert {"DATE_MISMATCH", "SNAPSHOT_MISMATCH"} <= codes(result)


@pytest.mark.parametrize("target,field,value", [("demand", "quantity", 300), ("attendance", "available", False), ("driver", "is_active", False)])
def test_stale_context(session, resources, target, field, value):
    old = context(session)
    setattr(resources[target], field, value); session.commit()
    new = context(session)
    assert "CONTEXT_STALE" in codes(DispatchCandidateValidator().validate(candidate(old, resources), old, current_context=new))


def test_context_tampering_rejected(session, resources):
    ctx = context(session)
    modified = ctx.model_copy(update={"daily_trip_limit": 1})
    assert "CONTEXT_INTEGRITY_ERROR" in codes(DispatchCandidateValidator().validate(candidate(ctx, resources), modified))


def test_reject_dirty_session_without_flushing(session, resources):
    resources["demand"].quantity = 350
    with pytest.raises(ValueError, match="Session"):
        context(session)
    assert resources["demand"] in session.dirty


def test_failed_validation_and_capture_only_select(session, resources):
    statements = []
    def capture(conn, cursor, statement, parameters, execution_context, executemany):
        statements.append(statement.lstrip().split()[0].upper())
    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        ctx = context(session)
        data = candidate(ctx, resources)
        data["trips"][0]["driver_id"] = resources["standby"].id
        assert not DispatchCandidateValidator().validate(data, ctx).is_valid
        assert statements and set(statements) == {"SELECT"}
        assert not session.new and not session.dirty and not session.deleted
    finally:
        event.remove(engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("status", [DeliveryDemandStatus.PUBLISHED, DeliveryDemandStatus.COMPLETED, DeliveryDemandStatus.CANCELLED, DeliveryDemandStatus.PLANNED])
def test_non_schedulable_status(session, resources, status):
    resources["demand"].status = status; session.commit()
    ctx = context(session)
    assert "DEMAND_NOT_SCHEDULABLE" in codes(DispatchCandidateValidator().validate(candidate(ctx, resources), ctx))


def test_planned_in_draft_remains_schedulable(session, resources):
    from app.domain.enums import DispatchPlanStatus
    r = resources
    plan = DispatchPlan(delivery_date=DAY, version=1, status=DispatchPlanStatus.DRAFT)
    session.add(plan); session.flush()
    order = DispatchOrder(plan_id=plan.id, vehicle_id=r["vehicle"].id, actual_driver_id=r["driver"].id,
                          route_id=r["route"].id, period=DeliveryPeriod.MORNING, trip_no=1, total_load=200)
    session.add(order); session.flush()
    session.add(DispatchOrderDetail(dispatch_order_id=order.id, delivery_demand_id=r["demand"].id, quantity=200))
    r["demand"].status = DeliveryDemandStatus.PLANNED
    session.commit()
    ctx = context(session)
    assert ctx.resource_records["plans"][0]["status"] == "DRAFT"
    assert DispatchCandidateValidator().validate(candidate(ctx, r), ctx).is_valid


def test_period_and_terrain_constraints(session, resources):
    ctx = context(session)
    data = candidate(ctx, resources)
    data["trips"][0]["period"] = "AFTERNOON"
    assert "PERIOD_MISMATCH" in codes(DispatchCandidateValidator().validate(data, ctx))
    session.delete(session.scalar(select(VehicleTypeTerrainPermission))); session.commit()
    ctx = context(session)
    assert "TERRAIN_NOT_ALLOWED" in codes(DispatchCandidateValidator().validate(candidate(ctx, resources), ctx))


def test_unknown_ids_and_overlap(session, resources):
    ctx = context(session)
    data = candidate(ctx, resources)
    data["trips"][0]["demand_ids"] = [999]
    assert {"DEMAND_NOT_FOUND", "MISSING_DEMAND"} <= codes(DispatchCandidateValidator().validate(data, ctx))
    data = candidate(ctx, resources, unassigned=[{"demand_id": resources["demand"].id, "explanation": "待处理"}])
    assert "ASSIGNED_AND_UNASSIGNED" in codes(DispatchCandidateValidator().validate(data, ctx))


@pytest.mark.parametrize("field,code", [("vehicle_id", "VEHICLE_NOT_FOUND"), ("route_id", "ROUTE_NOT_FOUND"), ("driver_id", "DRIVER_ASSIGNMENT_MISMATCH")])
def test_unknown_resource_ids(session, resources, field, code):
    ctx = context(session)
    data = candidate(ctx, resources)
    data["trips"][0][field] = 999
    assert code in codes(DispatchCandidateValidator().validate(data, ctx))


def test_no_effective_terrain(session, resources):
    session.delete(session.scalar(select(RouteTerrainConfig))); session.commit()
    ctx = context(session)
    assert "TERRAIN_NOT_CONFIGURED" in codes(DispatchCandidateValidator().validate(candidate(ctx, resources), ctx))


def test_substitute_schedule_without_confirmation(session, resources):
    r = resources
    session.add(DriverSchedule(date=DAY, period="MORNING", vehicle_id=r["vehicle"].id,
        driver_id=r["standby"].id, original_driver_id=r["driver"].id,
        kind="SUBSTITUTE", status="ACTIVE", actor_id=r["driver"].id))
    session.commit()
    ctx = context(session)
    assert "DRIVER_ASSIGNMENT_CONFLICT" in codes(DispatchCandidateValidator().validate(candidate(ctx, r), ctx))


def test_published_task_driver_conflict(session, resources):
    from app.domain.enums import DispatchPlanStatus
    r = resources
    other = Vehicle(code="V2", plate_number="湘A00002", vehicle_type_id=r["kind"].id, is_active=True)
    plan = DispatchPlan(delivery_date=DAY, version=1, status=DispatchPlanStatus.PUBLISHED)
    session.add_all([other, plan]); session.flush()
    session.add(DispatchOrder(plan_id=plan.id, vehicle_id=other.id, actual_driver_id=r["driver"].id,
        period=DeliveryPeriod.MORNING, trip_no=1, route_id=r["route"].id, total_load=200))
    session.commit()
    ctx = context(session)
    assert "DRIVER_ASSIGNED_TO_OTHER_VEHICLE" in codes(DispatchCandidateValidator().validate(candidate(ctx, r), ctx))


def test_stale_after_new_demand(session, resources):
    old = context(session)
    session.add(DeliveryDemand(date=DAY, store_id=resources["store"].id,
        period=DeliveryPeriod.AFTERNOON, quantity=200, status=DeliveryDemandStatus.PENDING))
    session.commit()
    new = context(session)
    assert "CONTEXT_STALE" in codes(DispatchCandidateValidator().validate(candidate(old, resources), old, current_context=new))


def test_duplicate_unassigned_and_model_instance_validation(session, resources):
    ctx = context(session)
    data = candidate(ctx, resources, trips=[], unassigned=[{"demand_id": resources["demand"].id, "explanation": "本次未分配"}] * 2)
    assert "DUPLICATE_UNASSIGNED" in codes(DispatchCandidateValidator().validate(data, ctx))
    parsed = DispatchCandidate.model_validate(candidate(ctx, resources))
    assert "INVALID_CANDIDATE" in codes(DispatchCandidateValidator().validate(parsed.model_copy(update={"candidate_id": ""}), ctx))


def test_read_context_supports_more_than_one_page(session, resources):
    for i in range(101):
        store = Store(code=f"FULL-{i}", name=f"全量门店{i}")
        session.add(store); session.flush()
        session.add(DeliveryDemand(date=DAY, store_id=store.id, period=DeliveryPeriod.MORNING,
                                  quantity=100, status=DeliveryDemandStatus.PENDING))
    session.commit()
    ctx = context(session)
    assert len(ctx.demands) == 102 and sum(d.schedulable for d in ctx.demands) == 102


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_candidate_ids_require_json_integers(session, resources, value):
    ctx = context(session)
    data = candidate(ctx, resources)
    data["trips"][0]["vehicle_id"] = value
    assert "INVALID_CANDIDATE" in codes(DispatchCandidateValidator().validate(data, ctx))


def test_invalid_context_date_and_no_model_weight_override(session, resources):
    with pytest.raises(ValidationError):
        DispatchContextService(session).load("not-a-date")
    ctx = context(session)
    data = candidate(ctx, resources)
    data["trips"][0]["total_load"] = 1
    assert "INVALID_CANDIDATE" in codes(DispatchCandidateValidator().validate(data, ctx))


def test_changed_role_refreshes_warmed_identity_map(session, resources):
    context(session)
    session.execute(update(User).where(User.id == resources["driver"].id)
                    .values(role=UserRole.ADMIN).execution_options(synchronize_session=False))
    session.commit()
    ctx = context(session)
    assert not DispatchCandidateValidator().validate(candidate(ctx, resources), ctx).is_valid
    assert not next(s for s in ctx.shifts if s.period == DeliveryPeriod.MORNING).available
