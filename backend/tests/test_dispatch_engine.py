from collections import Counter
from datetime import date
from decimal import Decimal

from app.dispatch_engine.load_optimizer import LoadOptimizer
from app.dispatch_engine.models import EngineDemand, EngineVehicle
from app.dispatch_engine.priority_rules import PriorityRules
from app.domain.enums import DeliveryPeriod, VehicleTypeCode


def make_vehicle(
    vehicle_id: int,
    code: VehicleTypeCode,
    name: str,
    min_load: str,
    max_load: str,
) -> EngineVehicle:
    return EngineVehicle(
        id=vehicle_id,
        code=f"V{vehicle_id}",
        plate_number=f"TEST{vehicle_id}",
        vehicle_type_id=vehicle_id,
        vehicle_type_code=code,
        vehicle_type_name=name,
        min_load=Decimal(min_load),
        max_load=Decimal(max_load),
    )


def make_demand(demand_id: int, quantity: str) -> EngineDemand:
    return EngineDemand(
        id=demand_id,
        date=date(2026, 9, 24),
        store_id=demand_id,
        store_code=f"S{demand_id}",
        store_name=f"门店{demand_id}",
        period=DeliveryPeriod.MORNING,
        quantity=Decimal(quantity),
    )


def test_load_optimizer_respects_minimum_and_maximum():
    vehicle = make_vehicle(1, VehicleTypeCode.BIG_VAN, "大包", "300", "420")
    optimizer = LoadOptimizer()

    valid = optimizer.build_load(
        vehicle, [make_demand(1, "220"), make_demand(2, "180")]
    )
    assert sum(item.quantity for item in valid) == Decimal("400")

    below_minimum = optimizer.build_load(vehicle, [make_demand(3, "299")])
    assert below_minimum == ()

    target_trip = optimizer.build_load(
        make_vehicle(2, VehicleTypeCode.SMALL_VAN, "小包", "1", "300"),
        [make_demand(4, "100"), make_demand(5, "100")],
        stop_at_minimum=True,
    )
    assert len(target_trip) == 1


def test_priority_rules_use_code_not_load_range_or_name():
    four_meter_two = make_vehicle(
        1, VehicleTypeCode.FOUR_METER, "可修改名称A", "600", "900"
    )
    large_bag = make_vehicle(
        2, VehicleTypeCode.BIG_VAN, "可修改名称B", "250", "500"
    )
    small_bag = make_vehicle(
        3, VehicleTypeCode.SMALL_VAN, "可修改名称C", "2", "350"
    )
    rules = PriorityRules()
    usage = Counter()

    counts = Counter()
    first = min(
        [four_meter_two, large_bag, small_bag],
        key=lambda vehicle: rules.vehicle_sort_key(
            vehicle, DeliveryPeriod.MORNING, counts, usage
        ),
    )
    assert first.id == large_bag.id

    counts[(DeliveryPeriod.MORNING, VehicleTypeCode.BIG_VAN)] = 1
    second = min(
        [four_meter_two, large_bag, small_bag],
        key=lambda vehicle: rules.vehicle_sort_key(
            vehicle, DeliveryPeriod.MORNING, counts, usage
        ),
    )
    assert second.id == small_bag.id

    counts[(DeliveryPeriod.MORNING, VehicleTypeCode.SMALL_VAN)] = 2
    third = min(
        [four_meter_two, large_bag, small_bag],
        key=lambda vehicle: rules.vehicle_sort_key(
            vehicle, DeliveryPeriod.MORNING, counts, usage
        ),
    )
    assert third.id == four_meter_two.id

    counts[(DeliveryPeriod.MORNING, VehicleTypeCode.FOUR_METER)] = 1
    assert rules.minimum_trip_targets == {
        VehicleTypeCode.FOUR_METER: 1,
        VehicleTypeCode.BIG_VAN: 1,
        VehicleTypeCode.SMALL_VAN: 2,
    }
    assert not rules.needs_minimum_trip(
        small_bag, DeliveryPeriod.MORNING, counts
    )
    assert rules.needs_minimum_trip(
        small_bag, DeliveryPeriod.AFTERNOON, counts
    )
