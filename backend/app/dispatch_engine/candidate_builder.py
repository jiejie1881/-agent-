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
from app.domain.constraints import CargoCompatibilityConstraint, TemperatureConstraint
from app.domain.constraints.base import DispatchValidationContext


class CandidateBuilder:
    def __init__(self) -> None:
        self.period_constraint = DemandPeriodConstraint()
        self.route_constraint = StoreRouteConstraint()
        self.terrain_constraint = VehicleTerrainConstraint()
        self.load_constraint = LoadRangeConstraint()
        self.cargo_constraint = CargoCompatibilityConstraint()
        self.temperature_constraint = TemperatureConstraint()

    def build(
        self,
        demands: list[EngineDemand],
        vehicles: list[EngineVehicle],
        routes: dict[int, EngineRoute],
        store_route_ids: dict[int, set[int]],
        permissions: set[tuple[int, int]],
        period: DeliveryPeriod,
        cargo_capabilities=None,
    ) -> CandidateBuildResult:
        result = CandidateBuildResult()
        reasons: dict[int, set[str]] = defaultdict(set)
        cargo_capabilities = cargo_capabilities or {}

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
                    if not self.terrain_constraint.is_satisfied(
                        vehicle, route, permissions
                    ):
                        continue
                    if not self.load_constraint.does_not_exceed_maximum(
                        vehicle, demand.quantity
                    ):
                        continue
                    capability = (
                        (True, None, None)
                        if demand.cargo_category_id == 0
                        else cargo_capabilities.get(
                            (vehicle.vehicle_type_id, demand.cargo_category_id)
                        )
                    )
                    context = DispatchValidationContext(
                        dispatch_date=demand.date,
                        vehicle_name=vehicle.plate_number,
                        vehicle_type_name=vehicle.vehicle_type_name,
                        demand_period=demand.period,
                        dispatch_period=period,
                        quantity=demand.quantity,
                        min_load=vehicle.min_load,
                        max_load=vehicle.max_load,
                        attendance_exists=True,
                        vehicle_available=True,
                        store_belongs_to_route=True,
                        terrain_configured=True,
                        terrain_name=route.terrain_name,
                        terrain_allowed=True,
                        cargo_category_id=demand.cargo_category_id,
                        cargo_category_name=demand.cargo_category_name,
                        cargo_capability_exists=capability is not None,
                        cargo_allowed=capability[0] if capability else False,
                        requires_temperature_control=demand.requires_temperature_control,
                        demand_min_temperature=demand.min_temperature,
                        demand_max_temperature=demand.max_temperature,
                        vehicle_min_temperature=capability[1] if capability else None,
                        vehicle_max_temperature=capability[2] if capability else None,
                    )
                    cargo_result = self.cargo_constraint.validate(context)
                    temperature_result = self.temperature_constraint.validate(context)
                    if not cargo_result.passed:
                        reasons[demand.id].add(cargo_result.reason or "车辆车型不支持当前货物类型")
                        continue
                    if not temperature_result.passed:
                        reasons[demand.id].add(temperature_result.reason or "车辆温控范围无法满足当前货物要求")
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

