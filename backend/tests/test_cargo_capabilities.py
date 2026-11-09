"""Retirement regressions: no category dependency, historical data kept."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.domain.dispatch_validator import DEFAULT_CONSTRAINTS
from app.models.cargo_category import CargoCategory
from app.models.delivery_demand import DeliveryDemand
from app.models.vehicle import VehicleTypeCargoCapability
from tests.test_auto_dispatch_api import create_terrain_route_and_stores, create_vehicle
from tests.test_dispatch_plan_adjustment import generate_adjustable_plan


def archive_category(session, demand_id):
    category = CargoCategory(code="FROZEN", name="旧冷冻分类", is_active=False)
    session.add(category)
    session.flush()
    demand = session.get(DeliveryDemand, demand_id)
    demand.cargo_category_id = category.id
    demand.requires_temperature_control = True
    demand.min_temperature = Decimal("-20")
    demand.max_temperature = Decimal("-18")
    session.commit()
    return category


def test_cargo_category_api_is_removed(client):
    assert client.get("/api/v1/cargo-categories").status_code == 404
    assert client.post("/api/v1/cargo-categories", json={"code": "X", "name": "X"}).status_code == 404
    assert client.get("/api/v1/vehicle-types/1/cargo-capabilities").status_code == 404


def test_delivery_demand_create_and_edit_without_categories(client, session):
    assert session.scalar(select(CargoCategory)) is None
    store = client.post("/api/v1/stores", json={"code": "S-CORE", "name": "配送店"}).json()
    created = client.post("/api/v1/delivery-demands", json={
        "date": "2026-09-24", "store_id": store["id"], "period": "MORNING", "quantity": 10,
    })
    assert created.status_code == 201
    demand = created.json()
    assert "cargo_category_id" not in demand and "requires_temperature_control" not in demand
    assert session.get(DeliveryDemand, demand["id"]).cargo_category_id is None
    updated = client.patch(f"/api/v1/delivery-demands/{demand['id']}", json={"quantity": 20})
    assert updated.status_code == 200 and Decimal(updated.json()["quantity"]) == 20


def test_only_core_dispatch_constraints_remain():
    names = {type(item).__name__ for item in DEFAULT_CONSTRAINTS}
    assert names == {"OperatingConstraint", "VehicleAvailableConstraint", "PeriodConstraint", "TerrainConstraint", "RouteConstraint", "LoadConstraint"}


def test_urgent_demand_is_dispatched_first(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [100, 100])
    urgent = stores[1][1]
    assert client.patch(f"/api/v1/delivery-demands/{urgent['id']}", json={"priority": "URGENT"}).status_code == 200
    create_vehicle(client, terrain["id"], "SMALL_VAN", "小包", 1, 100, "湘A10001")
    result = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"}).json()
    assert result["trips"][0]["stores"][0]["demand_id"] == urgent["id"]


def test_archived_category_and_temperature_do_not_block_dispatch_or_publish(client, session):
    terrain, _, stores = create_terrain_route_and_stores(client, [300])
    category = archive_category(session, stores[0][1]["id"])
    vehicle = create_vehicle(client, terrain["id"], "BIG_VAN", "普通大包", 300, 420, "湘A30001")
    session.add(VehicleTypeCargoCapability(vehicle_type_id=vehicle["vehicle_type_id"], cargo_category_id=category.id, is_allowed=False))
    session.commit()
    result = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"}).json()
    assert result["unassigned_demands"] == []
    assert client.post(f"/api/v1/dispatch-plans/{result['plan_id']}/publish").status_code == 200
    demand = session.get(DeliveryDemand, stores[0][1]["id"])
    assert demand.cargo_category_id == category.id and demand.min_temperature == Decimal("-20")


def test_manual_move_ignores_archived_transport_attributes(client, session):
    generated, plan, *_ = generate_adjustable_plan(client, [100, 100, 50, 50])
    source = next(order for order in plan["orders"] if len(order["details"]) > 1)
    target = next(order for order in plan["orders"] if order["id"] != source["id"])
    demand_id = source["details"][0]["delivery_demand_id"]
    archive_category(session, demand_id)
    result = client.post(f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand", json={
        "delivery_demand_id": demand_id, "source_order_id": source["id"], "target_order_id": target["id"],
    })
    assert result.status_code == 200


@pytest.mark.parametrize("field,value", [("cargo_category_id", 1), ("requires_temperature_control", True), ("min_temperature", -20), ("max_temperature", -18)])
def test_retired_fields_rejected_by_create_and_patch(client, field, value):
    store = client.post("/api/v1/stores", json={"code": "S-RETIRED", "name": "门店"}).json()
    core = {"date": "2026-09-24", "store_id": store["id"], "period": "MORNING", "quantity": 10}
    assert client.post("/api/v1/delivery-demands", json={**core, field: value}).status_code == 422
    created = client.post("/api/v1/delivery-demands", json=core).json()
    assert client.patch(f"/api/v1/delivery-demands/{created['id']}", json={field: value}).status_code == 422
