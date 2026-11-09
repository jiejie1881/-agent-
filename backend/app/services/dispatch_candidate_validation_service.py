"""Pure, deterministic validation over a server-owned snapshot. No DB or LLM."""
from collections import Counter
from decimal import Decimal

from pydantic import ValidationError

from app.domain.constraints.base import DispatchValidationContext
from app.domain.dispatch_validator import validate_dispatch
from app.schemas.dispatch_candidate import (
    POLICY_VERSION,
    CandidateValidationResult,
    CandidateViolation,
    DispatchCandidate,
    DispatchContext,
)


class DispatchCandidateValidator:
    def validate(self, candidate, context: DispatchContext, *,
                 current_context: DispatchContext | None = None) -> CandidateValidationResult:
        violations, loads = [], []

        def issue(code, message, **ids):
            violations.append(CandidateViolation(violation_code=code, message=message, related_ids=ids))

        def result(assigned=0, unassigned=0):
            return CandidateValidationResult(is_valid=not violations, violations=tuple(violations),
                snapshot_version=context.snapshot_version, assigned_count=assigned,
                unassigned_count=unassigned, trip_loads=tuple(loads),
                freshness_checked=current_context is not None)

        if context.policy_version != POLICY_VERSION or context.fingerprint() != context.snapshot_version:
            issue("CONTEXT_INTEGRITY_ERROR", "上下文内容或规则版本与快照标识不一致")
            return result()
        if current_context is not None:
            if current_context.fingerprint() != current_context.snapshot_version:
                issue("CONTEXT_INTEGRITY_ERROR", "当前上下文完整性校验失败")
                return result()
            if current_context.snapshot_version != context.snapshot_version:
                issue("CONTEXT_STALE", "调度数据已变化，必须重新规划")
                return result()
        try:
            candidate = DispatchCandidate.model_validate(candidate)
        except ValidationError as exc:
            issue("INVALID_CANDIDATE", "候选结构不合法：" + ", ".join(
                ".".join(map(str, e["loc"])) for e in exc.errors()))
            return result()
        if candidate.snapshot_version != context.snapshot_version:
            issue("SNAPSHOT_MISMATCH", "候选引用的快照与当前校验快照不一致")
        if candidate.delivery_date != context.delivery_date:
            issue("DATE_MISMATCH", "候选配送日期与上下文不一致")
        demands = {d.id: d for d in context.demands}
        vehicles = {v.id: v for v in context.vehicles}
        routes = {r.id: r for r in context.routes}
        stores = {s.id: s for s in context.stores}
        shifts = {(s.vehicle_id, s.period): s for s in context.shifts}
        assigned = Counter(d for trip in candidate.trips for d in trip.demand_ids)
        unassigned = Counter(u.demand_id for u in candidate.unassigned)
        expected = {d.id for d in context.demands if d.schedulable}
        for demand_id in sorted(set(assigned) | set(unassigned)):
            if demand_id not in demands:
                issue("DEMAND_NOT_FOUND", "需求不存在于当前日期上下文", demand_id=demand_id)
            elif demand_id not in expected:
                issue("DEMAND_NOT_SCHEDULABLE", "需求当前状态或草稿归属不可调度", demand_id=demand_id)
            if assigned[demand_id] > 1:
                issue("DUPLICATE_DEMAND", "需求被重复分配", demand_id=demand_id)
            if unassigned[demand_id] > 1:
                issue("DUPLICATE_UNASSIGNED", "未分配需求重复", demand_id=demand_id)
            if assigned[demand_id] and unassigned[demand_id]:
                issue("ASSIGNED_AND_UNASSIGNED", "需求同时已分配和未分配", demand_id=demand_id)
        for demand_id in sorted(expected - (set(assigned) | set(unassigned))):
            issue("MISSING_DEMAND", "候选遗漏输入需求", demand_id=demand_id)
        keys, driver_vehicles = set(), {}
        trip_counts = Counter(t.vehicle_id for t in candidate.trips)
        for index, trip in enumerate(candidate.trips):
            ids = {
                "trip_index": index,
                "trip_no": trip.trip_no,
                "vehicle_id": trip.vehicle_id,
                "driver_id": trip.driver_id,
                "route_id": trip.route_id,
            }
            key = (trip.vehicle_id, trip.period, trip.trip_no)
            if key in keys:
                issue("TRIP_CONFLICT", "同车辆同班次趟次编号重复", **ids)
            keys.add(key)
            driver_key = (trip.driver_id, trip.period)
            if driver_key in driver_vehicles and driver_vehicles[driver_key] != trip.vehicle_id:
                issue("DRIVER_VEHICLE_CONFLICT", "同司机同班次被安排到不同车辆", **ids)
            driver_vehicles[driver_key] = trip.vehicle_id
            vehicle, route = vehicles.get(trip.vehicle_id), routes.get(trip.route_id)
            total = sum((demands[d].quantity for d in trip.demand_ids if d in demands), Decimal(0))
            loads.append(total)
            if vehicle is None:
                issue("VEHICLE_NOT_FOUND", "车辆不存在", **ids)
                continue
            if not vehicle.is_active:
                issue("VEHICLE_INACTIVE", "车辆已停用", **ids)
            if not vehicle.type_active:
                issue("VEHICLE_TYPE_INACTIVE", "车型已停用", **ids)
            if vehicle.daily_trip_limit is not None and trip_counts[vehicle.id] > vehicle.daily_trip_limit:
                issue('DAILY_TRIP_LIMIT_EXCEEDED','车辆已超过配置的日趟次限制',**ids)
            if route is None:
                issue("ROUTE_NOT_FOUND", "线路不存在", **ids)
                continue
            shift = shifts.get((trip.vehicle_id, trip.period))
            if shift is None or not shift.available:
                issue(shift.violation_code if shift and shift.violation_code else "DRIVER_UNAVAILABLE",
                      shift.message if shift and shift.message else "该车辆班次没有有效司机", **ids)
            elif shift.driver_id != trip.driver_id:
                issue("DRIVER_ASSIGNMENT_MISMATCH", "候选司机不是该班次有效司机", **ids)
            for demand_id in trip.demand_ids:
                demand = demands.get(demand_id)
                if demand is None:
                    continue
                store = stores.get(demand.store_id)
                validation = validate_dispatch(DispatchValidationContext(
                    dispatch_date=context.delivery_date, vehicle_name=vehicle.plate_number,
                    vehicle_type_name=vehicle.vehicle_type_name, demand_period=demand.period,
                    dispatch_period=trip.period, quantity=total, min_load=vehicle.min_load,
                    max_load=vehicle.max_load, attendance_exists=vehicle.attendance_exists,
                    vehicle_available=vehicle.available,
                    store_belongs_to_route=bool(store and route.id in store.route_ids),
                    terrain_configured=route.terrain_id is not None,
                    terrain_name=route.terrain_name or f"ID={route.terrain_id}",
                    terrain_allowed=(vehicle.vehicle_type_id, route.terrain_id) in context.terrain_permissions,
                    vehicle_active=vehicle.is_active and vehicle.type_active and vehicle.operating_status == 'ACTIVE',
                    store_active=bool(store and store.is_active), route_active=route.is_active,
                    vehicle_route_allowed=vehicle.allowed_route_ids is None or route.id in vehicle.allowed_route_ids))
                for failure in validation.constraint_results:
                    if not failure.passed:
                        terrain_ids = {}
                        message = failure.reason or "业务约束失败"
                        if failure.code in {"TERRAIN_NOT_ALLOWED", "TERRAIN_NOT_CONFIGURED"}:
                            terrain_ids = {"vehicle_type_id": vehicle.vehicle_type_id,
                                           "terrain_id": route.terrain_id or "UNCONFIGURED",
                                           "period": trip.period.value}
                            message = (f"车辆{vehicle.code}(ID={vehicle.id})、车型{vehicle.vehicle_type_name}"
                                       f"(ID={vehicle.vehicle_type_id})、线路{route.code}(ID={route.id})：{message}")
                        issue(failure.code or "CONSTRAINT_FAILED", message,
                              demand_id=demand_id, **ids, **terrain_ids)
        return result(len(set(assigned) & expected), len(set(unassigned) & expected))
