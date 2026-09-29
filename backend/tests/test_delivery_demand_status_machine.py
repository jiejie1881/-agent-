import pytest

from app.domain.enums import DeliveryDemandStatus
from app.domain.exceptions import ConflictError
from app.models.delivery_demand import DeliveryDemand
from app.services.delivery_demand_status_service import DeliveryDemandStatusService
from tests.test_auto_dispatch_api import (
    create_terrain_route_and_stores,
    create_vehicle,
)
from tests.test_delivery_demand_api import create_store


def create_pending_demand(client):
    store = create_store(client)
    return client.post(
        "/api/v1/delivery-demands",
        json={
            "date": "2026-09-24",
            "store_id": store["id"],
            "period": "MORNING",
            "quantity": 100,
            "status": "PENDING",
        },
    ).json()


def test_patch_cannot_change_pending_directly_to_completed(client):
    demand = create_pending_demand(client)

    response = client.patch(
        f"/api/v1/delivery-demands/{demand['id']}",
        json={"status": "COMPLETED"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"
    unchanged = client.get(f"/api/v1/delivery-demands/{demand['id']}")
    assert unchanged.json()["status"] == "PENDING"


def test_demand_without_plan_cannot_be_published_by_patch(client):
    demand = create_pending_demand(client)

    response = client.patch(
        f"/api/v1/delivery-demands/{demand['id']}",
        json={"status": "PUBLISHED"},
    )

    assert response.status_code == 422
    assert client.get(
        f"/api/v1/delivery-demands/{demand['id']}"
    ).json()["status"] == "PENDING"


def test_business_actions_complete_legal_status_flow(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [100])
    create_vehicle(
        client, terrain["id"], "SMALL_VAN", "小包", 1, 300, "湘A001"
    )
    demand_id = stores[0][1]["id"]

    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    )
    assert generated.status_code == 200
    body = generated.json()
    assert client.get(
        f"/api/v1/delivery-demands/{demand_id}"
    ).json()["status"] == "PLANNED"

    published = client.post(
        f"/api/v1/dispatch-plans/{body['plan_id']}/publish"
    )
    assert published.status_code == 200
    assert published.json()["orders"][0]["details"][0]["status"] == "PUBLISHED"
    order_id = published.json()["orders"][0]["id"]
    assert client.get(
        f"/api/v1/delivery-demands/{demand_id}"
    ).json()["status"] == "PUBLISHED"

    started = client.post(
        f"/api/v1/dispatch-plans/{body['plan_id']}"
        f"/orders/{order_id}/start-delivery"
    )
    assert started.status_code == 200
    assert started.json()["orders"][0]["details"][0]["status"] == "DELIVERING"
    assert client.get(
        f"/api/v1/delivery-demands/{demand_id}"
    ).json()["status"] == "DELIVERING"

    completed = client.post(
        f"/api/v1/dispatch-plans/{body['plan_id']}"
        f"/orders/{order_id}/complete"
    )
    assert completed.status_code == 200
    assert completed.json()["orders"][0]["details"][0]["status"] == "COMPLETED"
    assert client.get(
        f"/api/v1/delivery-demands/{demand_id}"
    ).json()["status"] == "COMPLETED"


def test_complete_before_start_returns_clear_illegal_transition(client):
    terrain, _, _ = create_terrain_route_and_stores(client, [100])
    create_vehicle(
        client, terrain["id"], "SMALL_VAN", "小包", 1, 300, "湘A001"
    )
    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    published = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/publish"
    ).json()
    order_id = published["orders"][0]["id"]

    response = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}"
        f"/orders/{order_id}/complete"
    )

    assert response.status_code == 409
    assert "PUBLISHED" in response.json()["detail"]
    assert "不允许" in response.json()["detail"]


def test_plan_remains_published_while_detail_exposes_order_execution_status(client):
    terrain, _, _ = create_terrain_route_and_stores(client, [100])
    create_vehicle(
        client, terrain["id"], "SMALL_VAN", "小包", 1, 300, "湘A001"
    )
    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    plan_id = generated["plan_id"]
    published = client.post(f"/api/v1/dispatch-plans/{plan_id}/publish").json()
    order_id = published["orders"][0]["id"]

    client.post(
        f"/api/v1/dispatch-plans/{plan_id}/orders/{order_id}/start-delivery"
    )
    delivering = client.get(f"/api/v1/dispatch-plans/{plan_id}").json()
    assert delivering["status"] == "PUBLISHED"
    assert delivering["orders"][0]["details"][0]["status"] == "DELIVERING"

    client.post(
        f"/api/v1/dispatch-plans/{plan_id}/orders/{order_id}/complete"
    )
    completed = client.get(f"/api/v1/dispatch-plans/{plan_id}").json()
    assert completed["status"] == "PUBLISHED"
    assert completed["orders"][0]["details"][0]["status"] == "COMPLETED"


def test_illegal_status_transition_returns_clear_error(session):
    service = DeliveryDemandStatusService(session)
    demand = DeliveryDemand(id=1, status=DeliveryDemandStatus.PENDING)

    with pytest.raises(ConflictError, match="PENDING.*COMPLETED"):
        service.transition(demand, DeliveryDemandStatus.COMPLETED)


@pytest.mark.parametrize(
    "current_status",
    [
        DeliveryDemandStatus.PENDING,
        DeliveryDemandStatus.PLANNED,
        DeliveryDemandStatus.PUBLISHED,
        DeliveryDemandStatus.DELIVERING,
        DeliveryDemandStatus.COMPLETED,
    ],
)
def test_dedicated_cancel_action_cancels_demand(
    client, session, current_status
):
    demand = create_pending_demand(client)
    model = session.get(DeliveryDemand, demand["id"])
    model.status = current_status
    session.commit()

    cancelled = client.post(
        f"/api/v1/delivery-demands/{demand['id']}/cancel"
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


def test_cancel_action_is_idempotent(client):
    demand = create_pending_demand(client)
    first = client.post(f"/api/v1/delivery-demands/{demand['id']}/cancel")
    retry = client.post(f"/api/v1/delivery-demands/{demand['id']}/cancel")

    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json()["status"] == "CANCELLED"


def test_new_demand_defaults_to_pending_and_rejects_other_initial_status(client):
    store = create_store(client)
    payload = {
        "date": "2026-09-24",
        "store_id": store["id"],
        "period": "MORNING",
        "quantity": 100,
    }

    created = client.post("/api/v1/delivery-demands", json=payload)
    invalid = client.post(
        "/api/v1/delivery-demands",
        json={**payload, "period": "AFTERNOON", "status": "PLANNED"},
    )

    assert created.status_code == 201
    assert created.json()["status"] == "PENDING"
    assert invalid.status_code == 409
    assert invalid.json()["detail"] == "新建配送需求的状态必须为PENDING"
