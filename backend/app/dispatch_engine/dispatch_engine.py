from collections import Counter
from decimal import Decimal

from app.dispatch_engine.candidate_builder import CandidateBuilder
from app.dispatch_engine.load_optimizer import LoadOptimizer, PRIORITY_WEIGHT
from app.dispatch_engine.models import (
    DispatchEngineInput,
    DispatchEngineResult,
    EngineDemand,
    EngineRoute,
    EngineVehicle,
    TripPlan,
    UnassignedDemand,
)
from app.dispatch_engine.priority_rules import (
    PriorityRules,
)
from app.domain.enums import DeliveryPeriod, VehicleTypeCode


class DispatchEngine:
    def __init__(self) -> None:
        self.candidate_builder = CandidateBuilder()
        self.load_optimizer = LoadOptimizer()
        self.priority_rules = PriorityRules()

    def dispatch(self, engine_input: DispatchEngineInput) -> DispatchEngineResult:
        if not engine_input.vehicles:
            return self._no_vehicle_result(engine_input)

        trips: list[TripPlan] = []
        unassigned: list[UnassignedDemand] = []
        trip_counts: Counter[tuple[DeliveryPeriod, VehicleTypeCode]] = Counter()
        vehicle_trip_counts: Counter[tuple[int, DeliveryPeriod]] = Counter()

        for period in (DeliveryPeriod.MORNING, DeliveryPeriod.AFTERNOON):
            period_demands = [
                demand
                for demand in engine_input.demands
                if demand.period == period
            ]
            period_trips, period_unassigned = self._dispatch_period(
                period=period,
                demands=period_demands,
                vehicles=list(engine_input.vehicles),
                routes=engine_input.routes,
                store_route_ids=engine_input.store_route_ids,
                permissions=engine_input.permissions,
                trip_counts=trip_counts,
                vehicle_trip_counts=vehicle_trip_counts,
            )
            trips.extend(period_trips)
            unassigned.extend(period_unassigned)

        return DispatchEngineResult(
            dispatch_date=engine_input.dispatch_date,
            trips=tuple(trips),
            unassigned_demands=tuple(unassigned),
        )

    def _dispatch_period(
        self,
        period: DeliveryPeriod,
        demands: list[EngineDemand],
        vehicles: list[EngineVehicle],
        routes: dict[int, EngineRoute],
        store_route_ids: dict[int, set[int]],
        permissions: set[tuple[int, int]],
        trip_counts: Counter[tuple[DeliveryPeriod, VehicleTypeCode]],
        vehicle_trip_counts: Counter[tuple[int, DeliveryPeriod]],
    ) -> tuple[list[TripPlan], list[UnassignedDemand]]:
        candidate_result = self.candidate_builder.build(
            demands=demands,
            vehicles=vehicles,
            routes=routes,
            store_route_ids=store_route_ids,
            permissions=permissions,
            period=period,
        )
        options = {
            (option.demand_id, option.vehicle_id, option.route_id)
            for option in candidate_result.options
        }
        remaining = {demand.id: demand for demand in demands}
        trips: list[TripPlan] = []

        while remaining:
            proposal = self._select_trip_proposal(
                remaining=list(remaining.values()),
                vehicles=vehicles,
                routes=routes,
                options=options,
                period=period,
                trip_counts=trip_counts,
                vehicle_trip_counts=vehicle_trip_counts,
            )
            if proposal is None:
                break

            vehicle, route, loaded_demands = proposal
            total_load = sum(
                (item.quantity for item in loaded_demands), Decimal("0")
            )
            vehicle_trip_key = (vehicle.id, period)
            vehicle_trip_counts[vehicle_trip_key] += 1
            trip_counts[(period, vehicle.vehicle_type_code)] += 1
            trips.append(
                TripPlan(
                    vehicle=vehicle,
                    period=period,
                    trip_no=vehicle_trip_counts[vehicle_trip_key],
                    route=route,
                    demands=loaded_demands,
                    total_load=total_load,
                )
            )
            for item in loaded_demands:
                remaining.pop(item.demand.id, None)

        unassigned = []
        for demand in remaining.values():
            reasons = candidate_result.failure_reasons.get(demand.id)
            if reasons is None:
                reasons = ["候选需求组合无法达到车辆最低载重量"]
            unassigned.append(
                UnassignedDemand(demand=demand, reasons=tuple(reasons))
            )
        return trips, unassigned

    def _select_trip_proposal(
        self,
        remaining: list[EngineDemand],
        vehicles: list[EngineVehicle],
        routes: dict[int, EngineRoute],
        options: set[tuple[int, int, int]],
        period: DeliveryPeriod,
        trip_counts: Counter[tuple[DeliveryPeriod, VehicleTypeCode]],
        vehicle_trip_counts: Counter[tuple[int, DeliveryPeriod]],
    ) -> tuple[EngineVehicle, EngineRoute, tuple] | None:
        proposals: list[tuple[tuple, EngineVehicle, EngineRoute, tuple]] = []

        for vehicle in vehicles:
            if vehicle.daily_trip_limit is not None and sum(count for (vehicle_id,_),count in vehicle_trip_counts.items() if vehicle_id == vehicle.id) >= vehicle.daily_trip_limit:
                continue
            for route in routes.values():
                candidate_demands = [
                    demand
                    for demand in remaining
                    if (demand.id, vehicle.id, route.id) in options
                ]
                if not candidate_demands:
                    continue
                loaded = self.load_optimizer.build_load(
                    vehicle,
                    candidate_demands,
                    stop_at_minimum=self.priority_rules.needs_minimum_trip(
                        vehicle, period, trip_counts
                    ),
                )
                if not loaded:
                    continue
                total_load = sum(
                    (item.quantity for item in loaded), Decimal("0")
                )
                priority = self.priority_rules.vehicle_sort_key(
                    vehicle, period, trip_counts, vehicle_trip_counts
                )
                highest_demand_priority = max(
                    PRIORITY_WEIGHT[item.demand.priority] for item in loaded
                )
                proposal_key = (-highest_demand_priority, *priority, -total_load, route.id)
                proposals.append((proposal_key, vehicle, route, loaded))

        if not proposals:
            return None
        _, vehicle, route, loaded = min(proposals, key=lambda item: item[0])
        return vehicle, route, loaded

    @staticmethod
    def _no_vehicle_result(
        engine_input: DispatchEngineInput,
    ) -> DispatchEngineResult:
        return DispatchEngineResult(
            dispatch_date=engine_input.dispatch_date,
            trips=(),
            unassigned_demands=tuple(
                UnassignedDemand(
                    demand=demand,
                    reasons=("当天没有可出勤车辆",),
                )
                for demand in engine_input.demands
            ),
        )
