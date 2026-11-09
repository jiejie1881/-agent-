from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.enums import DispatchPlanStatus
from app.models.dispatch_plan import DispatchPlan
from tests.test_auto_dispatch_api import (
    create_terrain_route_and_stores,
    create_vehicle,
)


def setup_dispatchable_data(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [350])
    create_vehicle(
        client, terrain["id"], "BIG_VAN", "大包", 300, 420, "粤A30001"
    )
    return stores[0][1]


def test_auto_dispatch_persists_draft_plan_and_orders(client):
    demand = setup_dispatchable_data(client)

    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    )
    assert generated.status_code == 200
    generated_body = generated.json()
    assert generated_body["version"] == 1
    assert generated_body["status"] == "DRAFT"
    assert generated_body["plan_id"] > 0

    plan = client.get(f"/api/v1/dispatch-plans/{generated_body['plan_id']}")
    assert plan.status_code == 200
    plan_body = plan.json()
    assert plan_body["delivery_date"] == "2026-09-24"
    assert plan_body["version"] == 1
    assert plan_body["status"] == "DRAFT"
    assert plan_body["created_at"]
    assert plan_body["updated_at"]
    assert len(plan_body["orders"]) == 1
    assert plan_body["orders"][0]["total_load"] == "350.00"
    assert len(plan_body["orders"][0]["details"]) == 1
    assert plan_body["unassigned_demands"] == []
    demand_after_draft = client.get(
        f"/api/v1/delivery-demands/{demand['id']}"
    )
    assert demand_after_draft.json()["status"] == "PLANNED"


def test_one_dispatch_order_persists_multiple_demand_details(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [180, 170])
    create_vehicle(
        client, terrain["id"], "BIG_VAN", "大包", 300, 420, "粤A30001"
    )

    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    plan = client.get(f"/api/v1/dispatch-plans/{generated['plan_id']}")

    assert plan.status_code == 200
    assert len(plan.json()["orders"]) == 1
    details = plan.json()["orders"][0]["details"]
    assert len(details) == 2
    assert {item["delivery_demand_id"] for item in details} == {
        demand["id"] for _, demand in stores
    }
    assert sum(float(item["quantity"]) for item in details) == 350


def test_regeneration_increments_version_and_preserves_published_plan(client):
    demand = setup_dispatchable_data(client)

    first = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    published = client.post(
        f"/api/v1/dispatch-plans/{first['plan_id']}/publish"
    )
    assert published.status_code == 200
    assert published.json()["status"] == "PUBLISHED"
    assert client.get(
        f"/api/v1/delivery-demands/{demand['id']}"
    ).json()["status"] == "PUBLISHED"

    second = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["version"] == 2
    assert second_body["status"] == "DRAFT"
    assert second_body["plan_id"] != first["plan_id"]
    assert second_body["trips"] == []

    rejected = client.post(
        f"/api/v1/dispatch-plans/{second_body['plan_id']}/publish"
    )
    assert rejected.status_code == 409
    assert rejected.json()["issues"][0]["code"] == "NO_DISPATCH_ORDERS"

    original = client.get(f"/api/v1/dispatch-plans/{first['plan_id']}")
    assert original.status_code == 200
    assert original.json()["status"] == "PUBLISHED"
    assert original.json()["version"] == 1

    listed = client.get(
        "/api/v1/dispatch-plans?delivery_date=2026-09-24"
    )
    assert listed.status_code == 200
    assert [item["version"] for item in listed.json()] == [2, 1]


def test_versions_restart_from_one_for_a_different_date(client):
    setup_dispatchable_data(client)

    first = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    second = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    other_date = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-25"}
    ).json()

    assert (first["version"], second["version"]) == (1, 2)
    assert other_date["version"] == 1
    assert other_date["status"] == "DRAFT"


def test_history_and_specific_version_can_be_queried(client):
    setup_dispatchable_data(client)
    first = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    second = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()

    history = client.get("/api/v1/dispatch-plans/by-date/2026-09-24")
    version_one = client.get(
        "/api/v1/dispatch-plans/by-date/2026-09-24/versions/1"
    )

    assert history.status_code == 200
    assert [item["version"] for item in history.json()] == [2, 1]
    assert version_one.status_code == 200
    assert version_one.json()["id"] == first["plan_id"]
    assert version_one.json()["version"] == 1
    assert second["plan_id"] != first["plan_id"]
    assert client.get(
        "/api/v1/dispatch-plans/by-date/2026-09-24/versions/3"
    ).status_code == 404


def test_publishing_new_version_cancels_previous_published_plan(client):
    original_demand = setup_dispatchable_data(client)
    first = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    assert client.post(
        f"/api/v1/dispatch-plans/{first['plan_id']}/publish"
    ).status_code == 200

    new_demand = client.post(
        "/api/v1/delivery-demands",
        json={
            "date": "2026-09-24",
            "store_id": original_demand["store_id"],
            "period": "AFTERNOON",
            "quantity": 350,
        },
    )
    assert new_demand.status_code == 201
    second = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    assert len(second["trips"]) == 1
    published = client.post(
        f"/api/v1/dispatch-plans/{second['plan_id']}/publish"
    )

    assert published.status_code == 200
    assert published.json()["status"] == "PUBLISHED"
    assert client.get(
        f"/api/v1/dispatch-plans/{first['plan_id']}"
    ).json()["status"] == "CANCELLED"
    history = client.get(
        "/api/v1/dispatch-plans/by-date/2026-09-24"
    ).json()
    assert sum(item["status"] == "PUBLISHED" for item in history) == 1


def test_database_rejects_two_published_plans_for_same_date(session):
    session.add(
        DispatchPlan(
            delivery_date=date(2026, 9, 24),
            version=1,
            status=DispatchPlanStatus.PUBLISHED,
        )
    )
    session.commit()
    session.add(
        DispatchPlan(
            delivery_date=date(2026, 9, 24),
            version=2,
            status=DispatchPlanStatus.PUBLISHED,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_unassigned_demands_are_persisted_and_queryable(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [900])
    create_vehicle(
        client, terrain["id"], "FOUR_METER", "四米二", 630, 800, "粤A40001"
    )

    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    response = client.get(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/unassigned"
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["quantity"] == "900.00"
    assert response.json()[0]["reasons"]
    demand_id = stores[0][1]["id"]
    assert client.get(
        f"/api/v1/delivery-demands/{demand_id}"
    ).json()["status"] == "PENDING"


def test_cancelled_plan_cannot_be_published(client):
    demand = setup_dispatchable_data(client)
    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()

    cancelled = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert client.get(
        f"/api/v1/delivery-demands/{demand['id']}"
    ).json()["status"] == "PENDING"

    publish = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/publish"
    )
    assert publish.status_code == 409
