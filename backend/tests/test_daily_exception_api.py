from app.domain.enums import UserRole
from app.services.auth_service import AuthService
from tests.test_auth_rbac import login_as
from tests.test_dispatch_plan_publish_validation import setup_draft_plan


def test_report_api_returns_existing_draft_snapshot(client) -> None:
    data = setup_draft_plan(client)

    response = client.get(
        "/api/v1/daily-exceptions",
        params={"date": "2026-09-24"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reference_plan"]["id"] == data["generated"]["plan_id"]
    assert body["reference_plan"]["status"] == "DRAFT"
    assert body["pending_outside_reference_plan"]["count"] == 0
    assert body["plan_vehicle_unavailable"]["count"] == 0


def test_report_api_requires_read_permission(client, session) -> None:
    AuthService(session).create_user("report-viewer", "ViewerPass123!", UserRole.VIEWER)
    AuthService(session).create_user("report-dispatcher", "DispatchPass123!", UserRole.DISPATCHER)
    AuthService(session).create_user("report-driver", "DriverPass123!", UserRole.DRIVER)
    viewer = login_as(client, "report-viewer", "ViewerPass123!")
    dispatcher = login_as(client, "report-dispatcher", "DispatchPass123!")
    driver = login_as(client, "report-driver", "DriverPass123!")
    url = "/api/v1/daily-exceptions?date=2026-09-24"

    assert client.get(url, headers={"Authorization": f"Bearer {viewer}"}).status_code == 200
    assert client.get(url, headers={"Authorization": f"Bearer {dispatcher}"}).status_code == 200
    assert client.get(url).status_code == 200  # fixture's ADMIN token
    assert client.get(url, headers={"Authorization": f"Bearer {driver}"}).status_code == 403
    assert client.get(url, headers={"Authorization": ""}).status_code == 401


def test_report_api_rejects_invalid_date_and_example_limit(client) -> None:
    assert client.get("/api/v1/daily-exceptions?date=bad-date").status_code == 422
    assert client.get(
        "/api/v1/daily-exceptions",
        params={"date": "2026-09-24", "example_limit": 21},
    ).status_code == 422


def test_report_api_returns_empty_structure_without_plan(client) -> None:
    response = client.get(
        "/api/v1/daily-exceptions", params={"date": "2026-10-07"}
    )

    assert response.status_code == 200
    assert response.json()["reference_plan"] is None
    assert response.json()["failed_stops"] == {
        "count": 0, "examples": [], "truncated": False
    }
