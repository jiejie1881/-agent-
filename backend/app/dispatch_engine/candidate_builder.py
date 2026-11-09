from collections import defaultdict

from app.dispatch_engine.constraints import (
    DemandPeriodConstraint,
    LoadRangeConstraint,
    StoreRouteConstraint,
    VehicleTerrainConstraint,
)
from app.dispatch_engine.models import (
    CandidateBuildResult,
    CandidateOption,
    EngineDemand,
    EngineRoute,
    EngineVehicle,
)
from app.domain.enums import DeliveryPeriod


class CandidateBuilder:
    def __init__(self) -> None:
        self.period_constraint = DemandPeriodConstraint()
        self.route_constraint = StoreRouteConstraint()
        self.terrain_constraint = VehicleTerrainConstraint()
        self.load_constraint = LoadRangeConstraint()

    def build(
        self,
        demands: list[EngineDemand],
        vehicles: list[EngineVehicle],
        routes: dict[int, EngineRoute],
        store_route_ids: dict[int, set[int]],
        permissions: set[tuple[int, int]],
        period: DeliveryPeriod,
    ) -> CandidateBuildResult:
        result = CandidateBuildResult()
        reasons: dict[int, set[str]] = defaultdict(set)

        for demand in demands:
            if not self.period_constraint.is_satisfied(demand, period):
                continue

            route_ids = store_route_ids.get(demand.store_id, set())
            if not route_ids:
                reasons[demand.id].add("门店没有可用线路")
                continue

            configured_routes = [
                routes[route_id] for route_id in route_ids if route_id in routes
            ]
            if not configured_routes:
                reasons[demand.id].add("门店关联线路在配送日期没有生效的地形配置")
                continue

            for route in configured_routes:
                if not self.route_constraint.is_satisfied(
                    demand, route, store_route_ids
                ):
                    continue
                for vehicle in vehicles:
                    if vehicle.allowed_route_ids is not None and route.id not in vehicle.allowed_route_ids:
                        reasons[demand.id].add('线路不在车辆可运行范围')
                        continue
                    if not self.terrain_constraint.is_satisfied(
                        vehicle, route, permissions
                    ):
                        continue
                    if not self.load_constraint.does_not_exceed_maximum(
                        vehicle, demand.quantity
                    ):
                        continue
                    result.options.append(
                        CandidateOption(
                            demand_id=demand.id,
                            vehicle_id=vehicle.id,
                            route_id=route.id,
                        )
                    )

            if not any(option.demand_id == demand.id for option in result.options):
                if not reasons[demand.id]:
                    reasons[demand.id].add("没有同时满足线路地形和最大载重量的车辆")

        result.failure_reasons = {
            demand_id: sorted(items) for demand_id, items in reasons.items()
        }
        return result

