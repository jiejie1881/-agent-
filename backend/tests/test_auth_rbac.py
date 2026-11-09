from app.core.security import hash_password, verify_password
from app.domain.enums import UserRole
from app.services.auth_service import AuthService


def login_as(client, username: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_password_is_salted_and_verified():
    first = hash_password("SecurePass123!")
    second = hash_password("SecurePass123!")
    assert first != second
    assert "SecurePass123!" not in first
    assert verify_password("SecurePass123!", first)
    assert not verify_password("wrong-password", first)


def test_login_and_current_user(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "test-admin", "password": "AdminPass123!"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["role"] == "ADMIN"


def test_protected_api_requires_login(client):
    response = client.get("/api/v1/terrains", headers={"Authorization": ""})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_viewer_can_read_but_cannot_write(client, session):
    AuthService(session).create_user("viewer", "ViewerPass123!", UserRole.VIEWER)
    token = login_as(client, "viewer", "ViewerPass123!")
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/terrains", headers=headers).status_code == 200
    denied = client.post(
        "/api/v1/terrains",
        json={"code": "NORMAL", "name": "普通"},
        headers=headers,
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"
    assert client.post(
        "/api/v1/auto-dispatch",
        json={"date": "2026-09-25"},
        headers=headers,
    ).status_code == 403


def test_dispatcher_operates_daily_and_dispatch_but_not_master_data(client, session):
    AuthService(session).create_user(
        "dispatcher", "Dispatcher123!", UserRole.DISPATCHER
    )
    token = login_as(client, "dispatcher", "Dispatcher123!")
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/stores", headers=headers).status_code == 200
    assert client.post(
        "/api/v1/stores",
        json={"code": "S001", "name": "门店1"},
        headers=headers,
    ).status_code == 403

    demand_response = client.post(
        "/api/v1/delivery-demands",
        json={
            "date": "2026-09-25",
            "store_id": 999,
            "period": "MORNING",
            "quantity": 10,
        },
        headers=headers,
    )
    assert demand_response.status_code != 403
    dispatch_response = client.post(
        "/api/v1/auto-dispatch",
        json={"date": "2026-09-25"},
        headers=headers,
    )
    assert dispatch_response.status_code != 403


def test_invalid_token_is_rejected(client):
    response = client.get(
        "/api/v1/terrains",
        headers={"Authorization": "Bearer invalid.token.value"},
    )
    assert response.status_code == 401
