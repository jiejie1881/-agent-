from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryPeriod,
    DispatchPlanStatus,
    UserRole,
    VehicleTypeCode,
)
from app.models.audit_log import AuditLog
from app.models.cargo_category import CargoCategory
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchOrder, DispatchOrderDetail, DispatchPlan
from app.models.route import Route
from app.models.store import Store
from app.models.terrain import Terrain
from app.models.vehicle import Vehicle, VehicleType
from app.services.audit_log_service import AuditAction
from app.services.auth_service import AuthService


def _setup_driver_tasks(session):
    driver_a = AuthService(session).create_user(
        "driver-a", "DriverPass123!", UserRole.DRIVER
    )
    driver_b = AuthService(session).create_user(
        "driver-b", "DriverPass123!", UserRole.DRIVER
    )
    terrain = Terrain(code="NORMAL", name="普通")
    route = Route(code="DRIVER_ROUTE", name="司机线路")
    vehicle_type = VehicleType(
        code=VehicleTypeCode.SMALL_VAN,
        name="司机端小包",
        min_load=Decimal("1"),
        max_load=Decimal("300"),
    )
    session.add_all([terrain, route, vehicle_type])
    session.flush()
    vehicle_a = Vehicle(
        code="DRIVER_VEH_A",
        plate_number="湘A-D001",
        vehicle_type_id=vehicle_type.id,
        driver_user_id=driver_a.id,
    )
    vehicle_b = Vehicle(
        code="DRIVER_VEH_B",
        plate_number="湘A-D002",
        vehicle_type_id=vehicle_type.id,
        driver_user_id=driver_b.id,
    )
    store_a = Store(
        code="DRIVER_STORE_A",
        name="司机门店A",
        address="岳麓大道1号",
        contact_name="张三",
        contact_phone="13800000001",
        longitude=Decimal("112.9310000"),
        latitude=Decimal("28.2350000"),
    )
    store_b = Store(
        code="DRIVER_STORE_B",
        name="司机门店B",
        address="麓谷大道2号",
        longitude=Decimal("112.9000000"),
        latitude=Decimal("28.2100000"),
    )
    session.add_all([vehicle_a, vehicle_b, store_a, store_b])
    session.flush()
    cargo = session.scalar(select(CargoCategory).where(CargoCategory.code == "NORMAL"))
    today = date.today()
    demand_a = DeliveryDemand(
        date=today,
        store_id=store_a.id,
        period=DeliveryPeriod.MORNING,
        quantity=Decimal("100"),
        cargo_category_id=cargo.id,
        status=DeliveryDemandStatus.PUBLISHED,
    )
    demand_b = DeliveryDemand(
        date=today,
        store_id=store_b.id,
        period=DeliveryPeriod.AFTERNOON,
        quantity=Decimal("120"),
        cargo_category_id=cargo.id,
        status=DeliveryDemandStatus.PUBLISHED,
    )
    plan = DispatchPlan(
        delivery_date=today,
        version=1,
        status=DispatchPlanStatus.PUBLISHED,
    )
    session.add_all([demand_a, demand_b, plan])
    session.flush()
    order_a = DispatchOrder(
        plan_id=plan.id,
        vehicle_id=vehicle_a.id,
        period=DeliveryPeriod.MORNING,
        trip_no=1,
        route_id=route.id,
        total_load=Decimal("100"),
    )
    order_b = DispatchOrder(
        plan_id=plan.id,
        vehicle_id=vehicle_b.id,
        period=DeliveryPeriod.AFTERNOON,
        trip_no=1,
        route_id=route.id,
        total_load=Decimal("120"),
    )
    session.add_all([order_a, order_b])
    session.flush()
    session.add_all(
        [
            DispatchOrderDetail(
                dispatch_order_id=order_a.id,
                delivery_demand_id=demand_a.id,
                quantity=demand_a.quantity,
            ),
            DispatchOrderDetail(
                dispatch_order_id=order_b.id,
                delivery_demand_id=demand_b.id,
                quantity=demand_b.quantity,
            ),
        ]
    )
    session.commit()
    return driver_a, driver_b, order_a, order_b, demand_a, demand_b


def _driver_headers(client, username: str) -> dict[str, str]:
    response = client.post(
        "/api/driver/auth/login",
        json={"username": username, "password": "DriverPass123!"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _sign_only_stop(client, task_id: int, headers: dict[str, str]) -> None:
    stop_id = client.get(
        f"/api/driver/tasks/{task_id}", headers=headers
    ).json()["stops"][0]["id"]
    assert client.post(
        f"/api/driver/tasks/{task_id}/stops/{stop_id}/arrive", headers=headers
    ).status_code == 200
    assert client.post(
        f"/api/driver/tasks/{task_id}/stops/{stop_id}/sign",
        headers=headers,
        json={"receiver_name": "测试签收人"},
    ).status_code == 200


def test_driver_login_rejects_non_driver_account(client):
    response = client.post(
        "/api/driver/auth/login",
        json={"username": "test-admin", "password": "AdminPass123!"},
    )
    assert response.status_code == 401


def test_unbound_driver_login_has_clear_error_without_success_audit(client, session):
    driver = AuthService(session).create_user(
        "unbound-driver", "DriverPass123!", UserRole.DRIVER
    )
    response = client.post(
        "/api/driver/auth/login",
        json={"username": driver.username, "password": "DriverPass123!"},
    )
    assert response.status_code == 409
    assert response.json() == {
        "detail": "当前司机未绑定车辆，请联系管理员",
        "code": "DRIVER_VEHICLE_UNBOUND",
    }
    assert session.scalar(
        select(AuditLog).where(
            AuditLog.action == AuditAction.LOGIN,
            AuditLog.user_id == driver.id,
        )
    ) is None


def test_disabled_driver_login_does_not_reveal_account_state(client, session):
    driver = AuthService(session).create_user(
        "disabled-driver", "DriverPass123!", UserRole.DRIVER
    )
    driver.is_active = False
    session.commit()
    response = client.post(
        "/api/driver/auth/login",
        json={"username": driver.username, "password": "DriverPass123!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "用户名或密码错误"


def test_driver_can_only_list_own_today_tasks(client, session):
    _, _, order_a, order_b, *_ = _setup_driver_tasks(session)
    response = client.get(
        "/api/driver/tasks/today", headers=_driver_headers(client, "driver-a")
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [order_a.id]
    assert order_b.id not in {item["id"] for item in response.json()}


def test_driver_can_read_own_task_detail_with_stops(client, session):
    _, _, order_a, *_ = _setup_driver_tasks(session)
    response = client.get(
        f"/api/driver/tasks/{order_a.id}",
        headers=_driver_headers(client, "driver-a"),
    )
    assert response.status_code == 200
    assert response.json()["vehicle"]["plate_number"] == "湘A-D001"
    assert response.json()["stops"][0]["sequence"] == 1
    assert response.json()["stops"][0]["store_name"] == "司机门店A"


def test_driver_cannot_read_another_drivers_task(client, session):
    _, _, _, order_b, *_ = _setup_driver_tasks(session)
    response = client.get(
        f"/api/driver/tasks/{order_b.id}",
        headers=_driver_headers(client, "driver-a"),
    )
    assert response.status_code == 404


def test_driver_can_start_own_published_task(client, session):
    driver_a, _, order_a, _, demand_a, _ = _setup_driver_tasks(session)
    response = client.post(
        f"/api/driver/tasks/{order_a.id}/start",
        headers=_driver_headers(client, "driver-a"),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "DELIVERING"
    session.refresh(demand_a)
    assert demand_a.status == DeliveryDemandStatus.DELIVERING
    log = session.scalar(
        select(AuditLog).where(
            AuditLog.action == AuditAction.DELIVERY_STARTED,
            AuditLog.user_id == driver_a.id,
        )
    )
    assert log is not None


def test_driver_cannot_start_same_task_twice(client, session):
    _setup_driver_tasks(session)
    headers = _driver_headers(client, "driver-a")
    task_id = client.get("/api/driver/tasks/today", headers=headers).json()[0]["id"]
    assert client.post(f"/api/driver/tasks/{task_id}/start", headers=headers).status_code == 200
    repeated = client.post(f"/api/driver/tasks/{task_id}/start", headers=headers)
    assert repeated.status_code == 409


def test_driver_cannot_start_another_drivers_task(client, session):
    _, _, _, order_b, *_ = _setup_driver_tasks(session)
    response = client.post(
        f"/api/driver/tasks/{order_b.id}/start",
        headers=_driver_headers(client, "driver-a"),
    )
    assert response.status_code == 404


def test_driver_can_complete_own_delivering_task(client, session):
    _, _, order_a, *_ = _setup_driver_tasks(session)
    headers = _driver_headers(client, "driver-a")
    assert client.post(f"/api/driver/tasks/{order_a.id}/start", headers=headers).status_code == 200
    _sign_only_stop(client, order_a.id, headers)
    completed = client.post(f"/api/driver/tasks/{order_a.id}/complete", headers=headers)
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"


def test_driver_cannot_complete_same_task_twice(client, session):
    _, _, order_a, *_ = _setup_driver_tasks(session)
    headers = _driver_headers(client, "driver-a")
    client.post(f"/api/driver/tasks/{order_a.id}/start", headers=headers)
    _sign_only_stop(client, order_a.id, headers)
    assert client.post(f"/api/driver/tasks/{order_a.id}/complete", headers=headers).status_code == 200
    repeated = client.post(f"/api/driver/tasks/{order_a.id}/complete", headers=headers)
    assert repeated.status_code == 409


def test_driver_cannot_complete_another_drivers_task(client, session):
    _, _, _, order_b, *_ = _setup_driver_tasks(session)
    response = client.post(
        f"/api/driver/tasks/{order_b.id}/complete",
        headers=_driver_headers(client, "driver-a"),
    )
    assert response.status_code == 404


def test_driver_history_only_contains_own_tasks_and_supports_filters(client, session):
    _, _, order_a, order_b, *_ = _setup_driver_tasks(session)
    today = date.today().isoformat()
    response = client.get(
        f"/api/driver/tasks/history?start_date={today}&end_date={today}&page_size=10",
        headers=_driver_headers(client, "driver-a"),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [order_a.id]
    assert order_b.id not in {item["id"] for item in response.json()["items"]}

    future = (date.today() + timedelta(days=1)).isoformat()
    assert client.get(
        f"/api/driver/tasks/history?start_date={future}",
        headers=_driver_headers(client, "driver-a"),
    ).json()["total"] == 0


def test_driver_profile_returns_only_assigned_vehicle(client, session):
    _setup_driver_tasks(session)
    response = client.get(
        "/api/driver/profile", headers=_driver_headers(client, "driver-b")
    )
    assert response.status_code == 200
    assert response.json()["username"] == "driver-b"
    assert response.json()["vehicle"]["plate_number"] == "湘A-D002"


def test_driver_role_cannot_access_management_api(client, session):
    _setup_driver_tasks(session)
    response = client.get(
        "/api/v1/vehicles", headers=_driver_headers(client, "driver-a")
    )
    assert response.status_code == 403
