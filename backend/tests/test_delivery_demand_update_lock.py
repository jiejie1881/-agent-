from tests.test_auto_dispatch_api import (
    create_terrain_route_and_stores,
    create_vehicle,
)
from tests.test_delivery_demand_api import create_store


def assert_locked(response, status):
    assert response.status_code == 409
    assert response.json()["code"] == "DEMAND_LOCKED_BY_DISPATCH"
    assert status in response.json()["detail"]


def test_pending_demand_can_update_quantity(client):
    store = create_store(client)
    demand = client.post(
        "/api/v1/delivery-demands",
        json={
            "date": "2026-09-24",
            "store_id": store["id"],
            "period": "MORNING",
            "quantity": 100,
        },
    ).json()

    response = client.patch(
        f"/api/v1/delivery-demands/{demand['id']}",
        json={"quantity": 150},
    )

    assert response.status_code == 200
    assert response.json()["quantity"] == "150.00"
    assert response.json()["core_fields_editable"] is True


def test_planned_demand_cannot_update_quantity(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [100])
    create_vehicle(
        client, terrain["id"], "SMALL_VAN", "小包", 1, 300, "湘A001"
    )
    demand = stores[0][1]
    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    )
    assert generated.status_code == 200

    response = client.patch(
        f"/api/v1/delivery-demands/{demand['id']}",
        json={"quantity": 150},
    )

    assert_locked(response, "PLANNED")
    assert client.get(
        f"/api/v1/delivery-demands/{demand['id']}"
    ).json()["core_fields_editable"] is False


def test_published_demand_cannot_update_period(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [100])
    create_vehicle(
        client, terrain["id"], "SMALL_VAN", "小包", 1, 300, "湘A001"
    )
    demand = stores[0][1]
    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    published = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/publish"
    )
    assert published.status_code == 200

    response = client.patch(
        f"/api/v1/delivery-demands/{demand['id']}",
        json={"period": "AFTERNOON"},
    )

    assert_locked(response, "PUBLISHED")


def test_completed_demand_cannot_update_store(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [100])
    create_vehicle(
        client, terrain["id"], "SMALL_VAN", "小包", 1, 300, "湘A001"
    )
    demand = stores[0][1]
    replacement_store = client.post(
        "/api/v1/stores", json={"code": "S999", "name": "替换门店"}
    ).json()
    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    published = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/publish"
    ).json()
    order_id = published["orders"][0]["id"]
    client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}"
        f"/orders/{order_id}/start-delivery"
    )
    completed = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}"
        f"/orders/{order_id}/complete"
    )
    assert completed.status_code == 200

    response = client.patch(
        f"/api/v1/delivery-demands/{demand['id']}",
        json={"store_id": replacement_store["id"]},
    )

    assert_locked(response, "COMPLETED")


def test_cancelled_demand_keeps_core_fields_locked(client):
    store = create_store(client)
    demand = client.post(
        "/api/v1/delivery-demands",
        json={
            "date": "2026-09-24",
            "store_id": store["id"],
            "period": "MORNING",
            "quantity": 100,
        },
    ).json()
    cancelled = client.post(
        f"/api/v1/delivery-demands/{demand['id']}/cancel"
    )
    assert cancelled.status_code == 200

    response = client.patch(
        f"/api/v1/delivery-demands/{demand['id']}",
        json={"date": "2026-09-25"},
    )

    assert_locked(response, "CANCELLED")
