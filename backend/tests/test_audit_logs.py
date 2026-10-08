from sqlalchemy import select

from app.domain.enums import DeliveryStopStatus, UserRole
from app.models.audit_log import AuditLog
from app.models.dispatch_plan import DispatchOrderDetail
from app.services.audit_log_service import AuditAction
from app.services.auth_service import AuthService
from tests.test_delivery_demand_api import create_store
from tests.test_dispatch_plan_adjustment import (
    generate_adjustable_plan,
    move_payload,
)


def audit_actions(session) -> list[str]:
    session.expire_all()
    return list(session.scalars(select(AuditLog.action).order_by(AuditLog.id)))


def test_successful_login_is_audited_and_admin_can_query_logs(client, session):
    response = client.get("/api/v1/audit-logs")

    assert response.status_code == 200
    login_logs = [item for item in response.json() if item["action"] == "LOGIN"]
    assert login_logs
    assert login_logs[-1]["username"] == "test-admin"
    assert AuditAction.LOGIN in audit_actions(session)


def test_failed_delivery_demand_creation_does_not_add_success_audit(client, session):
    store = create_store(client)
    payload = {
        "date": "2026-09-27",
        "store_id": store["id"],
        "period": "MORNING",
        "quantity": 100,
    }
    assert client.post("/api/v1/delivery-demands", json=payload).status_code == 201
    count_before = audit_actions(session).count(
        AuditAction.DELIVERY_DEMAND_CREATED
    )

    failed = client.post("/api/v1/delivery-demands", json=payload)

    assert failed.status_code == 409
    assert audit_actions(session).count(
        AuditAction.DELIVERY_DEMAND_CREATED
    ) == count_before


def test_dispatch_lifecycle_writes_expected_audit_actions(client, session):
    generated, plan, *_ = generate_adjustable_plan(
        client, [100, 100, 50, 50]
    )
    source = next(order for order in plan["orders"] if len(order["details"]) == 2)
    target = next(order for order in plan["orders"] if order["id"] != source["id"])
    demand_id = source["details"][0]["delivery_demand_id"]

    moved = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand",
        json=move_payload(source, target, demand_id),
    )
    assert moved.status_code == 200
    published = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/publish"
    )
    assert published.status_code == 200
    order_id = published.json()["orders"][0]["id"]
    assert client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}"
        f"/orders/{order_id}/start-delivery"
    ).status_code == 200
    for stop in session.scalars(
        select(DispatchOrderDetail).where(
            DispatchOrderDetail.dispatch_order_id == order_id
        )
    ):
        stop.delivery_status = DeliveryStopStatus.SIGNED
    session.commit()
    assert client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}"
        f"/orders/{order_id}/complete"
    ).status_code == 200

    actions = set(audit_actions(session))
    assert {
        AuditAction.AUTO_DISPATCH_GENERATED,
        AuditAction.DISPATCH_DEMAND_MOVED,
        AuditAction.DISPATCH_PLAN_PUBLISHED,
        AuditAction.DELIVERY_STARTED,
        AuditAction.DELIVERY_COMPLETED,
    }.issubset(actions)


def test_cancel_is_audited_but_failed_move_is_not(client, session):
    generated, plan, *_ = generate_adjustable_plan(client, [100, 100])
    source, target = plan["orders"]
    failed_move = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand",
        json=move_payload(
            source, target, source["details"][0]["delivery_demand_id"]
        ),
    )
    assert failed_move.status_code == 409
    assert AuditAction.DISPATCH_DEMAND_MOVED not in audit_actions(session)

    cancelled = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/cancel"
    )
    assert cancelled.status_code == 200
    assert AuditAction.DISPATCH_PLAN_CANCELLED in audit_actions(session)


def test_user_permission_change_is_audited_without_sensitive_values(client, session):
    created = client.post(
        "/api/v1/users",
        json={
            "username": "audit-user",
            "password": "AuditUser123!",
            "role": "VIEWER",
            "is_active": True,
        },
    ).json()
    assert client.patch(
        f"/api/v1/users/{created['id']}",
        json={"role": "DISPATCHER"},
    ).status_code == 200

    logs = list(
        session.scalars(
            select(AuditLog).where(AuditLog.object_id == created["id"])
        )
    )
    assert {log.action for log in logs} >= {
        AuditAction.USER_CREATED,
        AuditAction.USER_UPDATED,
    }
    assert "password" not in str([log.changes for log in logs]).lower()


def test_non_admin_cannot_read_audit_logs(client, session):
    AuthService(session).create_user(
        "audit-viewer", "AuditViewer123!", UserRole.VIEWER
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "audit-viewer", "password": "AuditViewer123!"},
    ).json()["access_token"]

    response = client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
