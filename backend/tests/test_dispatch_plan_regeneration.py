from tests.test_auto_dispatch_api import (
    create_terrain_route_and_stores,
    create_vehicle,
)
from app.domain.enums import DeliveryDemandStatus
from app.models.delivery_demand import DeliveryDemand


def setup_pending_demands(client, count):
    terrain, _, stores = create_terrain_route_and_stores(client, [1] * count)
    create_vehicle(
        client,
        terrain["id"],
        "SMALL_VAN",
        "小包",
        1,
        300,
        "湘A001",
    )
    return [demand for _, demand in stores]


def assigned_demand_ids(dispatch_result):
    return {
        store["demand_id"]
        for trip in dispatch_result["trips"]
        for store in trip["stores"]
    }


def persisted_demand_ids(plan):
    return {
        detail["delivery_demand_id"]
        for order in plan["orders"]
        for detail in order["details"]
    }


def test_same_day_v2_recalculates_all_100_demands_and_preserves_v1(client):
    demands = setup_pending_demands(client, 100)
    expected_ids = {demand["id"] for demand in demands}

    version_one = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    version_two = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()

    assert version_one["version"] == 1
    assert version_two["version"] == 2
    assert assigned_demand_ids(version_one) == expected_ids
    assert assigned_demand_ids(version_two) == expected_ids

    persisted_v1 = client.get(
        "/api/v1/dispatch-plans/by-date/2026-09-24/versions/1"
    ).json()
    persisted_v2 = client.get(
        "/api/v1/dispatch-plans/by-date/2026-09-24/versions/2"
    ).json()
    assert persisted_demand_ids(persisted_v1) == expected_ids
    assert persisted_demand_ids(persisted_v2) == expected_ids


def test_completed_demand_does_not_enter_new_draft_version(client, session):
    demands = setup_pending_demands(client, 3)
    version_one = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    completed_id = demands[0]["id"]
    session.get(DeliveryDemand, completed_id).status = DeliveryDemandStatus.COMPLETED
    session.commit()

    version_two = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()

    assert completed_id in assigned_demand_ids(version_one)
    assert completed_id not in assigned_demand_ids(version_two)
    assert assigned_demand_ids(version_two) == {
        demands[1]["id"],
        demands[2]["id"],
    }


def test_cancelled_demand_does_not_enter_new_draft_version(client, session):
    demands = setup_pending_demands(client, 3)
    version_one = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    cancelled_id = demands[0]["id"]
    session.get(DeliveryDemand, cancelled_id).status = DeliveryDemandStatus.CANCELLED
    session.commit()

    version_two = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()

    assert cancelled_id in assigned_demand_ids(version_one)
    assert cancelled_id not in assigned_demand_ids(version_two)
    assert assigned_demand_ids(version_two) == {
        demands[1]["id"],
        demands[2]["id"],
    }


def test_unowned_planned_demand_is_not_treated_as_draft_occupancy(client, session):
    demands = setup_pending_demands(client, 1)
    demand_id = demands[0]["id"]
    session.get(DeliveryDemand, demand_id).status = DeliveryDemandStatus.PLANNED
    session.commit()

    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()

    assert generated["trips"] == []
    assert generated["unassigned_demands"] == []


def test_cancelling_one_of_two_drafts_keeps_shared_demands_planned(client):
    demands = setup_pending_demands(client, 2)
    version_one = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    version_two = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()

    cancelled_v1 = client.post(
        f"/api/v1/dispatch-plans/{version_one['plan_id']}/cancel"
    )
    assert cancelled_v1.status_code == 200
    assert all(
        client.get(f"/api/v1/delivery-demands/{demand['id']}").json()["status"]
        == "PLANNED"
        for demand in demands
    )

    cancelled_v2 = client.post(
        f"/api/v1/dispatch-plans/{version_two['plan_id']}/cancel"
    )
    assert cancelled_v2.status_code == 200
    assert all(
        client.get(f"/api/v1/delivery-demands/{demand['id']}").json()["status"]
        == "PENDING"
        for demand in demands
    )
