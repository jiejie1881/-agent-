from decimal import Decimal

from app.domain.enums import DeliveryPeriod
from app.models.dispatch_plan import DispatchOrder, DispatchOrderDetail
from tests.test_auto_dispatch_api import (
    create_terrain_route_and_stores,
    create_vehicle,
)


def setup_draft_plan(client):
    terrain, route, stores = create_terrain_route_and_stores(client, [350])
    vehicle = create_vehicle(
        client, terrain["id"], "BIG_VAN", "大包", 300, 420, "湘A001"
    )
    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    plan = client.get(
        f"/api/v1/dispatch-plans/{generated['plan_id']}"
    ).json()
    return {
        "terrain": terrain,
        "route": route,
        "store": stores[0][0],
        "demand": stores[0][1],
        "vehicle": vehicle,
        "generated": generated,
        "order": plan["orders"][0],
    }


def issue_codes(response):
    body = response.json()
    assert body["code"] == "DISPATCH_PLAN_VALIDATION_FAILED"
    return {issue["code"] for issue in body["issues"]}


def assert_publish_rolled_back(client, data):
    plan_id = data["generated"]["plan_id"]
    assert client.get(
        f"/api/v1/dispatch-plans/{plan_id}"
    ).json()["status"] == "DRAFT"
    assert client.get(
        f"/api/v1/delivery-demands/{data['demand']['id']}"
    ).json()["status"] == "PLANNED"


def test_valid_draft_plan_can_be_published(client):
    data = setup_draft_plan(client)

    response = client.post(
        f"/api/v1/dispatch-plans/{data['generated']['plan_id']}/publish"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "PUBLISHED"


def test_vehicle_becoming_unavailable_blocks_publish_and_rolls_back(client):
    data = setup_draft_plan(client)
    attendances = client.get(
        "/api/v1/vehicle-attendances",
        params={"date": "2026-09-24", "vehicle_id": data["vehicle"]["id"]},
    ).json()
    changed = client.patch(
        f"/api/v1/vehicle-attendances/{attendances[0]['id']}",
        json={"available": False},
    )
    assert changed.status_code == 200

    response = client.post(
        f"/api/v1/dispatch-plans/{data['generated']['plan_id']}/publish"
    )

    assert response.status_code == 409
    assert "VEHICLE_NOT_AVAILABLE" in issue_codes(response)
    assert_publish_rolled_back(client, data)


def test_removed_store_route_blocks_publish(client):
    data = setup_draft_plan(client)
    removed = client.delete(
        f"/api/v1/stores/{data['store']['id']}/routes/{data['route']['id']}"
    )
    assert removed.status_code == 204

    response = client.post(
        f"/api/v1/dispatch-plans/{data['generated']['plan_id']}/publish"
    )

    assert response.status_code == 409
    assert "ROUTE_NOT_ALLOWED" in issue_codes(response)
    assert_publish_rolled_back(client, data)


def test_lowered_vehicle_type_max_load_blocks_publish(client):
    data = setup_draft_plan(client)
    changed = client.patch(
        f"/api/v1/vehicle-types/{data['vehicle']['vehicle_type_id']}",
        json={"max_load": 340},
    )
    assert changed.status_code == 200

    response = client.post(
        f"/api/v1/dispatch-plans/{data['generated']['plan_id']}/publish"
    )

    assert response.status_code == 409
    assert "OVERLOAD" in issue_codes(response)
    assert_publish_rolled_back(client, data)


def test_total_load_mismatch_blocks_publish(client, session):
    data = setup_draft_plan(client)
    order = session.get(DispatchOrder, data["order"]["id"])
    order.total_load = Decimal("349")
    session.commit()

    response = client.post(
        f"/api/v1/dispatch-plans/{data['generated']['plan_id']}/publish"
    )

    assert response.status_code == 409
    assert "TOTAL_LOAD_MISMATCH" in issue_codes(response)
    assert_publish_rolled_back(client, data)


def test_publish_returns_all_detected_issues(client, session):
    data = setup_draft_plan(client)
    attendances = client.get(
        "/api/v1/vehicle-attendances",
        params={"date": "2026-09-24", "vehicle_id": data["vehicle"]["id"]},
    ).json()
    client.patch(
        f"/api/v1/vehicle-attendances/{attendances[0]['id']}",
        json={"available": False},
    )
    client.delete(
        f"/api/v1/stores/{data['store']['id']}/routes/{data['route']['id']}"
    )
    order = session.get(DispatchOrder, data["order"]["id"])
    order.total_load = Decimal("349")
    session.commit()

    response = client.post(
        f"/api/v1/dispatch-plans/{data['generated']['plan_id']}/publish"
    )

    assert response.status_code == 409
    assert {
        "VEHICLE_NOT_AVAILABLE",
        "ROUTE_NOT_ALLOWED",
        "TOTAL_LOAD_MISMATCH",
    }.issubset(issue_codes(response))
    assert_publish_rolled_back(client, data)


def test_duplicate_demand_across_orders_blocks_publish(client, session):
    data = setup_draft_plan(client)
    duplicate_order = DispatchOrder(
        plan_id=data["generated"]["plan_id"],
        vehicle_id=data["vehicle"]["id"],
        period=DeliveryPeriod.MORNING,
        trip_no=2,
        route_id=data["route"]["id"],
        total_load=Decimal("350"),
    )
    session.add(duplicate_order)
    session.flush()
    session.add(
        DispatchOrderDetail(
            dispatch_order_id=duplicate_order.id,
            delivery_demand_id=data["demand"]["id"],
            quantity=Decimal("350"),
        )
    )
    session.commit()

    response = client.post(
        f"/api/v1/dispatch-plans/{data['generated']['plan_id']}/publish"
    )

    assert response.status_code == 409
    assert "DUPLICATE_DEMAND" in issue_codes(response)


def test_cancelled_demand_is_invalid_for_publish(client):
    data = setup_draft_plan(client)
    cancelled = client.post(
        f"/api/v1/delivery-demands/{data['demand']['id']}/cancel"
    )
    assert cancelled.status_code == 200

    response = client.post(
        f"/api/v1/dispatch-plans/{data['generated']['plan_id']}/publish"
    )

    assert response.status_code == 409
    assert "INVALID_DELIVERY_DEMAND_STATUS" in issue_codes(response)
