"""Greedy comparison over the exact snapshot; never use AutoDispatchService."""
from time import perf_counter
from collections import Counter

from app.agent.dispatch_workflow import metrics
from app.dispatch_engine.dispatch_engine import DispatchEngine
from app.dispatch_engine.models import (
    DispatchEngineInput,
    EngineDemand,
    EngineRoute,
    EngineVehicle,
)
from app.domain.enums import DeliveryPeriod, VehicleTypeCode
from app.schemas.agent_dispatch import ShadowComparison
from app.schemas.dispatch_candidate import DispatchCandidate
from app.services.dispatch_candidate_validation_service import (
    DispatchCandidateValidator,
)


def compare_greedy(context):
    started = perf_counter()
    try:
        stores = {s.id: s for s in context.stores}
        shifts = {(s.vehicle_id, s.period): s for s in context.shifts}
        routes = {r.id: EngineRoute(r.id, r.code, r.name, r.terrain_id, "")
                  for r in context.routes if r.terrain_id is not None and r.is_active}
        trips, unassigned = [], []
        counts = Counter()
        for period in DeliveryPeriod:
            demands = tuple(EngineDemand(d.id, d.date, d.store_id, stores[d.store_id].code,
                stores[d.store_id].name, d.period, d.quantity, d.priority)
                for d in context.demands if d.schedulable and d.period == period)
            vehicles = tuple(EngineVehicle(v.id, v.code, v.plate_number, v.vehicle_type_id,
                v.vehicle_type_code, v.vehicle_type_name, v.min_load, v.max_load,
                allowed_route_ids=v.allowed_route_ids, daily_trip_limit=(v.daily_trip_limit-counts[v.id]) if v.daily_trip_limit is not None else None)
                for v in context.vehicles if shifts[(v.id, period)].available and v.operating_status == 'ACTIVE'
                and v.is_active and v.type_active and (v.daily_trip_limit is None or counts[v.id] < v.daily_trip_limit))
            result = DispatchEngine().dispatch(DispatchEngineInput(context.delivery_date,
                demands, vehicles, routes, {s.id: set(s.route_ids) if s.is_active else set() for s in context.stores},
                set(context.terrain_permissions)))
            counts.update(t.vehicle.id for t in result.trips)
            trips.extend({
                "vehicle_id": t.vehicle.id,
                "driver_id": shifts[(t.vehicle.id, period)].driver_id,
                "period": t.period,
                "trip_no": t.trip_no,
                "route_id": t.route.id,
                "demand_ids": [d.demand.id for d in t.demands],
            } for t in result.trips)
            unassigned.extend({
                "demand_id": u.demand.id,
                "explanation": "；".join(u.reasons) or "未找到合法组合",
            } for u in result.unassigned_demands)
        candidate = DispatchCandidate(candidate_id="greedy-comparison", delivery_date=context.delivery_date,
            snapshot_version=context.snapshot_version, trips=trips, unassigned=unassigned)
        validation = DispatchCandidateValidator().validate(candidate, context)
        return ShadowComparison(status="PASS" if validation.is_valid else "BLOCKED",
            metrics=metrics(candidate, context, validation), validation=validation,
            elapsed_ms=(perf_counter() - started) * 1000,
            error_code=None if validation.is_valid else "GREEDY_INVALID")
    except Exception:  # noqa: BLE001 -- optional comparison cannot turn failure into valid metrics.
        return ShadowComparison(status="BLOCKED", error_code="GREEDY_COMPARISON_ERROR",
                                elapsed_ms=(perf_counter() - started) * 1000)
