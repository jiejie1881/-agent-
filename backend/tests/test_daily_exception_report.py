from datetime import date

import pytest

from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryFailureReason,
    DeliveryStopStatus,
    DispatchPlanStatus,
)
from app.domain.exceptions import ConflictError, NotFoundError
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchOrderDetail, DispatchPlan
from app.models.vehicle_attendance import VehicleAttendance
from app.services.daily_exception_service import DailyExceptionService
from tests.test_auto_dispatch_api import create_terrain_route_and_stores
from tests.test_dispatch_plan_publish_validation import setup_draft_plan


REPORT_DATE = date(2026, 9, 24)


def test_no_plan_reports_only_pending_demand(client, session) -> None:
    store = client.post(
        "/api/v1/stores", json={"code": "S001", "name": "门店一"}
    ).json()
    demand = client.post(
        "/api/v1/delivery-demands",
        json={
            "date": "2026-09-24",
            "store_id": store["id"],
            "period": "MORNING",
            "quantity": 100,
        },
    ).json()

    report = DailyExceptionService(session).report(REPORT_DATE)

    assert report["reference_plan"] is None
    assert report["pending_outside_reference_plan"]["count"] == 1
    assert report["pending_outside_reference_plan"]["examples"][0]["demand_id"] == demand["id"]
    assert report["failed_stops"]["count"] == 0


def test_draft_is_labeled_and_vehicle_attendance_change_is_reported(client, session) -> None:
    data = setup_draft_plan(client)
    plan_id = data["generated"]["plan_id"]
    attendance = client.get(
        "/api/v1/vehicle-attendances",
        params={"date": "2026-09-24", "vehicle_id": data["vehicle"]["id"]},
    ).json()[0]
    assert client.patch(
        f"/api/v1/vehicle-attendances/{attendance['id']}",
        json={"available": False},
    ).status_code == 200

    report = DailyExceptionService(session).report(REPORT_DATE)

    assert report["reference_plan"] == {
        "id": plan_id,
        "version": 1,
        "status": "DRAFT",
        "selection": "AUTO_PUBLISHED_OR_LATEST_DRAFT",
    }
    assert report["plan_vehicle_unavailable"]["count"] == 1
    assert report["plan_vehicle_unavailable"]["examples"][0]["attendance"] == "UNAVAILABLE"
    assert report["pending_outside_reference_plan"]["count"] == 0
    assert any("DRAFT" in note for note in report["notices"])


def test_published_plan_selected_over_new_draft_and_failed_stop_reported(client, session) -> None:
    data = setup_draft_plan(client)
    published_id = data["generated"]["plan_id"]
    assert client.post(f"/api/v1/dispatch-plans/{published_id}/publish").status_code == 200
    new_plan = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"}).json()
    assert new_plan["plan_id"] != published_id
    stop = session.get(DispatchOrderDetail, data["order"]["details"][0]["id"])
    stop.delivery_status = DeliveryStopStatus.FAILED
    stop.failure_reason = DeliveryFailureReason.STORE_CLOSED
    session.commit()

    report = DailyExceptionService(session).report(REPORT_DATE)

    assert report["reference_plan"]["id"] == published_id
    assert report["reference_plan"]["status"] == "PUBLISHED"
    assert report["failed_stops"]["count"] == 1
    assert report["failed_stops"]["examples"][0]["failure_reason"] == "STORE_CLOSED"


def test_explicit_plan_date_mismatch_and_missing_plan_rejected(client, session) -> None:
    data = setup_draft_plan(client)
    service = DailyExceptionService(session)

    with pytest.raises(ConflictError, match="配送日期"):
        service.report(date(2026, 9, 25), data["generated"]["plan_id"])
    with pytest.raises(NotFoundError):
        service.report(REPORT_DATE, 99999)


def test_report_examples_are_bounded_without_losing_counts(client, session) -> None:
    for index in range(3):
        store = client.post(
            "/api/v1/stores",
            json={"code": f"S{index:03}", "name": f"门店{index}"},
        ).json()
        client.post(
            "/api/v1/delivery-demands",
            json={
                "date": "2026-09-24",
                "store_id": store["id"],
                "period": "MORNING",
                "quantity": 100,
            },
        )

    report = DailyExceptionService(session).report(REPORT_DATE, example_limit=1)

    assert report["pending_outside_reference_plan"]["count"] == 3
    assert len(report["pending_outside_reference_plan"]["examples"]) == 1
    assert report["pending_outside_reference_plan"]["truncated"] is True


def test_plan_unassigned_is_distinct_from_new_pending_demand(client, session) -> None:
    _, _, stores = create_terrain_route_and_stores(client, [125])
    generated = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"}).json()
    assert generated["unassigned_demands"]
    new_store = client.post(
        "/api/v1/stores", json={"code": "S999", "name": "新门店"}
    ).json()
    new_demand = client.post(
        "/api/v1/delivery-demands",
        json={
            "date": "2026-09-24",
            "store_id": new_store["id"],
            "period": "MORNING",
            "quantity": 75,
        },
    ).json()

    report = DailyExceptionService(session).report(REPORT_DATE)

    assert report["plan_unassigned"]["count"] == 1
    assert report["plan_unassigned"]["examples"][0]["demand_id"] == stores[0][1]["id"]
    assert report["pending_outside_reference_plan"]["count"] == 1
    assert report["pending_outside_reference_plan"]["examples"][0]["demand_id"] == new_demand["id"]


def test_latest_draft_is_selected_and_old_draft_planned_demand_is_outside(client, session) -> None:
    data = setup_draft_plan(client)
    latest = DispatchPlan(
        delivery_date=REPORT_DATE, version=2, status=DispatchPlanStatus.DRAFT
    )
    session.add(latest)
    session.commit()

    report = DailyExceptionService(session).report(REPORT_DATE)

    assert report["reference_plan"]["id"] == latest.id
    assert report["reference_plan"]["version"] == 2
    assert report["pending_outside_reference_plan"]["count"] == 1
    assert report["pending_outside_reference_plan"]["examples"][0]["demand_id"] == data["demand"]["id"]


def test_cancelled_demand_is_not_current_plan_unassigned(client, session) -> None:
    _, _, stores = create_terrain_route_and_stores(client, [125])
    generated = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"}).json()
    assert generated["unassigned_demands"]
    demand = session.get(DeliveryDemand, stores[0][1]["id"])
    demand.status = DeliveryDemandStatus.CANCELLED
    session.commit()

    report = DailyExceptionService(session).report(REPORT_DATE)

    assert report["plan_unassigned"]["count"] == 0
    assert report["pending_outside_reference_plan"]["count"] == 0


def test_inactive_vehicle_and_type_are_reported_without_duplicate_order(client, session) -> None:
    data = setup_draft_plan(client)
    assert client.patch(
        f"/api/v1/vehicles/{data['vehicle']['id']}", json={"is_active": False}
    ).status_code == 200
    assert client.patch(
        f"/api/v1/vehicle-types/{data['vehicle']['vehicle_type_id']}",
        json={"is_active": False},
    ).status_code == 200

    report = DailyExceptionService(session).report(REPORT_DATE)

    assert report["plan_vehicle_unavailable"]["count"] == 1
    assert report["plan_vehicle_unavailable"]["examples"][0]["issues"] == [
        "VEHICLE_INACTIVE",
        "VEHICLE_TYPE_INACTIVE",
    ]
    assert report["plan_vehicle_unavailable"]["examples"][0]["attendance"] == "AVAILABLE"


def test_missing_attendance_is_reported(client, session) -> None:
    data = setup_draft_plan(client)
    attendance = session.query(VehicleAttendance).filter_by(
        date=REPORT_DATE, vehicle_id=data["vehicle"]["id"]
    ).one()
    session.delete(attendance)
    session.commit()

    report = DailyExceptionService(session).report(REPORT_DATE)

    assert report["plan_vehicle_unavailable"]["count"] == 1
    assert report["plan_vehicle_unavailable"]["examples"][0]["issues"] == [
        "ATTENDANCE_MISSING"
    ]


def test_empty_date_has_four_empty_sections(client, session) -> None:
    report = DailyExceptionService(session).report(REPORT_DATE)

    assert report["reference_plan"] is None
    for name in (
        "plan_unassigned",
        "pending_outside_reference_plan",
        "plan_vehicle_unavailable",
        "failed_stops",
    ):
        assert report[name] == {"count": 0, "examples": [], "truncated": False}
