from base64 import b64decode
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.domain.enums import DeliveryDemandStatus, DeliveryPeriod
from app.models.audit_log import AuditLog
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchOrderDetail
from app.models.store import Store
from app.services.audit_log_service import AuditAction
from tests.test_driver_api import _driver_headers, _setup_driver_tasks


PNG_1X1 = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _start_task(client, order_id: int, username: str = "driver-a"):
    headers = _driver_headers(client, username)
    assert client.post(
        f"/api/driver/tasks/{order_id}/start", headers=headers
    ).status_code == 200
    task = client.get(f"/api/driver/tasks/{order_id}", headers=headers).json()
    return headers, task


def _add_second_stop(session, order, *, code: str = "DRIVER_STORE_C"):
    store = Store(code=code, name=f"{code}门店", address="岳麓区测试地址")
    session.add(store)
    session.flush()
    demand = DeliveryDemand(
        date=date.today(),
        store_id=store.id,
        period=order.period,
        quantity=Decimal("50"),
        status=DeliveryDemandStatus.PUBLISHED,
    )
    session.add(demand)
    session.flush()
    detail = DispatchOrderDetail(
        dispatch_order_id=order.id,
        delivery_demand_id=demand.id,
        quantity=demand.quantity,
    )
    session.add(detail)
    order.total_load += demand.quantity
    session.commit()
    return detail


def test_owner_can_arrive_and_pending_changes_to_arrived(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    stop_id = task["stops"][0]["id"]
    response = client.post(
        f"/api/driver/tasks/{order.id}/stops/{stop_id}/arrive", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == "ARRIVED"
    assert response.json()["arrived_at"]


def test_other_driver_cannot_arrive_stop(client, session):
    _, _, order_a, *_ = _setup_driver_tasks(session)
    _, task = _start_task(client, order_a.id)
    response = client.post(
        f"/api/driver/tasks/{order_a.id}/stops/{task['stops'][0]['id']}/arrive",
        headers=_driver_headers(client, "driver-b"),
    )
    assert response.status_code == 404


def test_arrived_stop_can_be_signed(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    stop_id = task["stops"][0]["id"]
    client.post(f"/api/driver/tasks/{order.id}/stops/{stop_id}/arrive", headers=headers)
    response = client.post(
        f"/api/driver/tasks/{order.id}/stops/{stop_id}/sign",
        headers=headers,
        json={
            "receiver_name": "张三",
            "receiver_phone": "13800000000",
            "remark": "货物完好",
        },
    )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == "SIGNED"
    assert response.json()["receiver_name"] == "张三"
    assert response.json()["signed_at"]


def test_pending_stop_cannot_be_signed_directly(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    response = client.post(
        f"/api/driver/tasks/{order.id}/stops/{task['stops'][0]['id']}/sign",
        headers=headers,
        json={"receiver_name": "张三"},
    )
    assert response.status_code == 409


def test_signed_stop_cannot_be_signed_twice(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    stop_id = task["stops"][0]["id"]
    client.post(f"/api/driver/tasks/{order.id}/stops/{stop_id}/arrive", headers=headers)
    payload = {"receiver_name": "张三"}
    assert client.post(
        f"/api/driver/tasks/{order.id}/stops/{stop_id}/sign",
        headers=headers,
        json=payload,
    ).status_code == 200
    assert client.post(
        f"/api/driver/tasks/{order.id}/stops/{stop_id}/sign",
        headers=headers,
        json=payload,
    ).status_code == 409


def test_pending_stop_can_fail_with_reason(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    response = client.post(
        f"/api/driver/tasks/{order.id}/stops/{task['stops'][0]['id']}/fail",
        headers=headers,
        json={"failure_reason": "STORE_CLOSED"},
    )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == "FAILED"
    assert response.json()["failure_reason"] == "STORE_CLOSED"


def test_arrived_stop_can_fail(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    stop_id = task["stops"][0]["id"]
    client.post(f"/api/driver/tasks/{order.id}/stops/{stop_id}/arrive", headers=headers)
    response = client.post(
        f"/api/driver/tasks/{order.id}/stops/{stop_id}/fail",
        headers=headers,
        json={"failure_reason": "REJECTED", "remark": "门店拒收"},
    )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == "FAILED"


def test_fail_requires_reason_and_other_requires_remark(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    url = f"/api/driver/tasks/{order.id}/stops/{task['stops'][0]['id']}/fail"
    assert client.post(url, headers=headers, json={}).status_code == 422
    assert client.post(
        url, headers=headers, json={"failure_reason": "OTHER"}
    ).status_code == 422


def test_other_driver_cannot_sign_or_fail_stop(client, session):
    _, _, order_a, *_ = _setup_driver_tasks(session)
    owner_headers, task = _start_task(client, order_a.id)
    stop_id = task["stops"][0]["id"]
    client.post(
        f"/api/driver/tasks/{order_a.id}/stops/{stop_id}/arrive",
        headers=owner_headers,
    )
    other_headers = _driver_headers(client, "driver-b")
    assert client.post(
        f"/api/driver/tasks/{order_a.id}/stops/{stop_id}/sign",
        headers=other_headers,
        json={"receiver_name": "越权"},
    ).status_code == 404
    assert client.post(
        f"/api/driver/tasks/{order_a.id}/stops/{stop_id}/fail",
        headers=other_headers,
        json={"failure_reason": "REJECTED"},
    ).status_code == 404


def test_task_cannot_complete_with_pending_stop(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, _ = _start_task(client, order.id)
    response = client.post(f"/api/driver/tasks/{order.id}/complete", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "仍有未完成配送的门店"


def test_task_cannot_complete_with_arrived_stop(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    client.post(
        f"/api/driver/tasks/{order.id}/stops/{task['stops'][0]['id']}/arrive",
        headers=headers,
    )
    response = client.post(f"/api/driver/tasks/{order.id}/complete", headers=headers)
    assert response.status_code == 409


def test_task_can_complete_when_all_stops_signed(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    stop_id = task["stops"][0]["id"]
    client.post(f"/api/driver/tasks/{order.id}/stops/{stop_id}/arrive", headers=headers)
    client.post(
        f"/api/driver/tasks/{order.id}/stops/{stop_id}/sign",
        headers=headers,
        json={"receiver_name": "张三"},
    )
    assert client.post(
        f"/api/driver/tasks/{order.id}/complete", headers=headers
    ).status_code == 200


def test_task_can_complete_with_signed_and_failed_stops(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    _add_second_stop(session, order)
    headers, task = _start_task(client, order.id)
    first, second = task["stops"]
    client.post(
        f"/api/driver/tasks/{order.id}/stops/{first['id']}/arrive", headers=headers
    )
    client.post(
        f"/api/driver/tasks/{order.id}/stops/{first['id']}/sign",
        headers=headers,
        json={"receiver_name": "张三"},
    )
    client.post(
        f"/api/driver/tasks/{order.id}/stops/{second['id']}/fail",
        headers=headers,
        json={"failure_reason": "STORE_CLOSED"},
    )
    assert client.post(
        f"/api/driver/tasks/{order.id}/complete", headers=headers
    ).status_code == 200


def test_proof_upload_checks_ownership_and_returns_safe_url(
    client, session, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "app.services.delivery_stop_service.delivery_proof_directory",
        lambda: tmp_path,
    )
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    stop_id = task["stops"][0]["id"]
    client.post(f"/api/driver/tasks/{order.id}/stops/{stop_id}/arrive", headers=headers)

    assert client.post(
        f"/api/driver/tasks/{order.id}/stops/{stop_id}/proofs",
        headers=_driver_headers(client, "driver-b"),
        files={"file": ("evidence.png", PNG_1X1, "image/png")},
    ).status_code == 404

    uploaded = client.post(
        f"/api/driver/tasks/{order.id}/stops/{stop_id}/proofs",
        headers=headers,
        files={"file": ("../../unsafe.png", PNG_1X1, "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["url"].startswith("/uploads/delivery-proofs/")
    assert "unsafe" not in uploaded.json()["url"]
    assert len(list(tmp_path.iterdir())) == 1


def test_non_image_proof_is_rejected(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.delivery_stop_service.delivery_proof_directory",
        lambda: tmp_path,
    )
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    stop_id = task["stops"][0]["id"]
    client.post(f"/api/driver/tasks/{order.id}/stops/{stop_id}/arrive", headers=headers)
    response = client.post(
        f"/api/driver/tasks/{order.id}/stops/{stop_id}/proofs",
        headers=headers,
        files={"file": ("proof.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 409
    assert list(tmp_path.iterdir()) == []


def test_oversized_proof_is_rejected(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.delivery_stop_service.delivery_proof_directory",
        lambda: tmp_path,
    )
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    stop_id = task["stops"][0]["id"]
    client.post(f"/api/driver/tasks/{order.id}/stops/{stop_id}/arrive", headers=headers)
    too_large = b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024)
    response = client.post(
        f"/api/driver/tasks/{order.id}/stops/{stop_id}/proofs",
        headers=headers,
        files={"file": ("large.png", too_large, "image/png")},
    )
    assert response.status_code == 409
    assert list(tmp_path.iterdir()) == []


def test_stop_actions_write_audit_logs(client, session):
    _, _, order, *_ = _setup_driver_tasks(session)
    _add_second_stop(session, order, code="DRIVER_STORE_AUDIT")
    headers, task = _start_task(client, order.id)
    first, second = task["stops"]
    client.post(
        f"/api/driver/tasks/{order.id}/stops/{first['id']}/arrive", headers=headers
    )
    client.post(
        f"/api/driver/tasks/{order.id}/stops/{first['id']}/sign",
        headers=headers,
        json={"receiver_name": "审计签收人"},
    )
    client.post(
        f"/api/driver/tasks/{order.id}/stops/{second['id']}/fail",
        headers=headers,
        json={"failure_reason": "ADDRESS_ERROR"},
    )
    actions = set(session.scalars(select(AuditLog.action)))
    assert {
        AuditAction.DELIVERY_STOP_ARRIVED,
        AuditAction.DELIVERY_STOP_SIGNED,
        AuditAction.DELIVERY_STOP_FAILED,
    }.issubset(actions)


def test_each_stop_accepts_at_most_three_proofs(
    client, session, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "app.services.delivery_stop_service.delivery_proof_directory",
        lambda: tmp_path,
    )
    _, _, order, *_ = _setup_driver_tasks(session)
    headers, task = _start_task(client, order.id)
    stop_id = task["stops"][0]["id"]
    client.post(f"/api/driver/tasks/{order.id}/stops/{stop_id}/arrive", headers=headers)
    url = f"/api/driver/tasks/{order.id}/stops/{stop_id}/proofs"
    for index in range(3):
        assert client.post(
            url,
            headers=headers,
            files={"file": (f"proof-{index}.png", PNG_1X1, "image/png")},
        ).status_code == 200
    fourth = client.post(
        url,
        headers=headers,
        files={"file": ("proof-4.png", PNG_1X1, "image/png")},
    )
    assert fourth.status_code == 409
    assert len(list(tmp_path.iterdir())) == 3
