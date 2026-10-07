from dataclasses import replace
from decimal import Decimal

from app.domain.constraints import CargoCompatibilityConstraint, TemperatureConstraint
from app.domain.constraints.base import DispatchValidationContext
from app.domain.enums import DeliveryPeriod
from tests.test_auto_dispatch_api import create_terrain_route_and_stores, create_vehicle


def category(client, code):
    return next(
        item for item in client.get("/api/v1/cargo-categories").json()
        if item["code"] == code
    )


def capability_payload(category_id, *, allowed=True, minimum=None, maximum=None):
    return {
        "cargo_category_id": category_id,
        "is_allowed": allowed,
        "min_temperature": minimum,
        "max_temperature": maximum,
    }


def base_context(**changes):
    context = DispatchValidationContext(
        dispatch_date=__import__("datetime").date(2026, 9, 24),
        vehicle_name="湘A001", vehicle_type_name="冷藏车",
        demand_period=DeliveryPeriod.MORNING,
        dispatch_period=DeliveryPeriod.MORNING,
        quantity=Decimal("100"), min_load=Decimal("1"), max_load=Decimal("300"),
        attendance_exists=True, vehicle_available=True,
        store_belongs_to_route=True, terrain_configured=True,
        terrain_name="普通", terrain_allowed=True,
        cargo_category_id=2, cargo_category_name="生鲜",
        cargo_capability_exists=True, cargo_allowed=True,
    )
    return replace(context, **changes)


def test_cargo_category_create_duplicate_and_deactivate(client):
    created = client.post(
        "/api/v1/cargo-categories",
        json={"code": "MEDICINE", "name": "医药", "description": "测试"},
    )
    assert created.status_code == 201
    duplicate = client.post(
        "/api/v1/cargo-categories", json={"code": "medicine", "name": "重复"}
    )
    assert duplicate.status_code == 409
    disabled = client.delete(f"/api/v1/cargo-categories/{created.json()['id']}")
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False


def test_delivery_demand_temperature_validation(client):
    store = client.post("/api/v1/stores", json={"code": "S-TEMP", "name": "温控店"}).json()
    fresh = category(client, "FRESH")
    missing = client.post(
        "/api/v1/delivery-demands",
        json={"date": "2026-09-24", "store_id": store["id"], "period": "MORNING", "quantity": 10, "cargo_category_id": fresh["id"], "requires_temperature_control": True},
    )
    assert missing.status_code == 422
    invalid = client.post(
        "/api/v1/delivery-demands",
        json={"date": "2026-09-24", "store_id": store["id"], "period": "MORNING", "quantity": 10, "cargo_category_id": fresh["id"], "requires_temperature_control": True, "min_temperature": 8, "max_temperature": 0},
    )
    assert invalid.status_code == 422
    valid = client.post(
        "/api/v1/delivery-demands",
        json={"date": "2026-09-24", "store_id": store["id"], "period": "MORNING", "quantity": 10, "cargo_category_id": fresh["id"], "priority": "HIGH", "requires_temperature_control": True, "min_temperature": 0, "max_temperature": 8},
    )
    assert valid.status_code == 201
    assert valid.json()["cargo_category"]["code"] == "FRESH"


def test_cargo_and_temperature_constraints_are_independent():
    cargo = CargoCompatibilityConstraint()
    temperature = TemperatureConstraint()
    assert cargo.validate(base_context()).passed
    assert not cargo.validate(base_context(cargo_allowed=False)).passed
    assert temperature.validate(base_context(requires_temperature_control=False)).passed
    assert temperature.validate(base_context(requires_temperature_control=True, demand_min_temperature=Decimal("0"), demand_max_temperature=Decimal("8"), vehicle_min_temperature=Decimal("-5"), vehicle_max_temperature=Decimal("10"))).passed
    failed = temperature.validate(base_context(requires_temperature_control=True, demand_min_temperature=Decimal("-20"), demand_max_temperature=Decimal("-15"), vehicle_min_temperature=Decimal("-10"), vehicle_max_temperature=Decimal("5")))
    assert not failed.passed
    assert failed.code == "TEMPERATURE_NOT_SUPPORTED"


def test_urgent_demand_is_dispatched_first(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [100, 100])
    urgent = stores[1][1]
    assert client.patch(
        f"/api/v1/delivery-demands/{urgent['id']}", json={"priority": "URGENT"}
    ).status_code == 200
    create_vehicle(client, terrain["id"], "SMALL_VAN", "小包", 1, 100, "湘A10001")
    result = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"}).json()
    assert result["trips"][0]["stores"][0]["demand_id"] == urgent["id"]


def test_frozen_demand_only_uses_compatible_vehicle_and_publish_revalidates(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [300])
    demand = stores[0][1]
    frozen = category(client, "FROZEN")
    assert client.patch(
        f"/api/v1/delivery-demands/{demand['id']}",
        json={"cargo_category_id": frozen["id"], "requires_temperature_control": True, "min_temperature": -20, "max_temperature": -15},
    ).status_code == 200
    vehicle = create_vehicle(client, terrain["id"], "BIG_VAN", "冷冻大包", 300, 420, "湘A30001")
    vehicle_type_id = vehicle["vehicle_type_id"]
    configured = client.put(
        f"/api/v1/vehicle-types/{vehicle_type_id}/cargo-capabilities",
        json={"capabilities": [capability_payload(frozen["id"], minimum=-25, maximum=5)]},
    )
    assert configured.status_code == 200
    result = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"}).json()
    assert result["unassigned_demands"] == []
    assert result["trips"][0]["vehicle"]["id"] == vehicle["id"]

    client.put(
        f"/api/v1/vehicle-types/{vehicle_type_id}/cargo-capabilities",
        json={"capabilities": [capability_payload(frozen["id"], allowed=False)]},
    )
    published = client.post(f"/api/v1/dispatch-plans/{result['plan_id']}/publish")
    assert published.status_code == 409
    assert "CARGO_NOT_ALLOWED" in {item["code"] for item in published.json()["issues"]}


def test_manual_move_cannot_bypass_cargo_compatibility(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [300, 100])
    frozen = category(client, "FROZEN")
    frozen_demand = stores[0][1]
    client.patch(f"/api/v1/delivery-demands/{frozen_demand['id']}", json={"cargo_category_id": frozen["id"]})
    big = create_vehicle(client, terrain["id"], "BIG_VAN", "冷冻大包", 1, 500, "湘A30001")
    small = create_vehicle(client, terrain["id"], "SMALL_VAN", "普通小包", 1, 500, "湘A10001")
    client.put(f"/api/v1/vehicle-types/{big['vehicle_type_id']}/cargo-capabilities", json={"capabilities": [capability_payload(frozen["id"])]})
    result = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"}).json()
    plan = client.get(f"/api/v1/dispatch-plans/{result['plan_id']}").json()
    source = next(order for order in plan["orders"] if any(item["delivery_demand_id"] == frozen_demand["id"] for item in order["details"]))
    target = next(order for order in plan["orders"] if order["vehicle"]["id"] == small["id"])
    moved = client.post(
        f"/api/v1/dispatch-plans/{result['plan_id']}/move-demand",
        json={"delivery_demand_id": frozen_demand["id"], "source_order_id": source["id"], "target_order_id": target["id"]},
    )
    assert moved.status_code == 409
    assert "CARGO_NOT_ALLOWED" in {item["code"] for item in moved.json()["issues"]}
