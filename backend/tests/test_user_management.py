from app.domain.enums import UserRole
from app.services.auth_service import AuthService


def login(client, username: str, password: str):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def test_admin_can_create_update_and_disable_user(client):
    created = client.post(
        "/api/v1/users",
        json={
            "username": "operator",
            "password": "Operator123!",
            "role": "VIEWER",
            "is_active": True,
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/users/{user_id}",
        json={"role": "DISPATCHER", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "DISPATCHER"
    assert updated.json()["is_active"] is False
    assert login(client, "operator", "Operator123!").status_code == 401


def test_non_admin_cannot_list_or_modify_users(client, session):
    dispatcher = AuthService(session).create_user(
        "dispatcher-user", "Dispatcher123!", UserRole.DISPATCHER
    )
    token = login(client, "dispatcher-user", "Dispatcher123!").json()[
        "access_token"
    ]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/users", headers=headers).status_code == 403
    assert client.patch(
        f"/api/v1/users/{dispatcher.id}",
        json={"role": "ADMIN"},
        headers=headers,
    ).status_code == 403


def test_admin_cannot_change_own_role_or_disable_self(client):
    current = client.get("/api/v1/auth/me").json()
    role_response = client.patch(
        f"/api/v1/users/{current['id']}", json={"role": "VIEWER"}
    )
    disable_response = client.patch(
        f"/api/v1/users/{current['id']}", json={"is_active": False}
    )

    assert role_response.status_code == 409
    assert "自己的角色" in role_response.json()["detail"]
    assert disable_response.status_code == 409
    assert "当前登录用户" in disable_response.json()["detail"]


def test_refresh_token_issues_new_token_and_rejects_access_token(client):
    authenticated = login(client, "test-admin", "AdminPass123!").json()
    refreshed = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": authenticated["refresh_token"]},
    )
    wrong_type = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": authenticated["access_token"]},
    )

    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]
    assert refreshed.json()["refresh_token"]
    assert client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {refreshed.json()['access_token']}"
        },
    ).status_code == 200
    assert wrong_type.status_code == 401


def test_change_password_invalidates_old_access_and_refresh_tokens(client):
    authenticated = login(client, "test-admin", "AdminPass123!").json()
    headers = {
        "Authorization": f"Bearer {authenticated['access_token']}"
    }

    changed = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "AdminPass123!",
            "new_password": "NewAdminPass456!",
        },
        headers=headers,
    )

    assert changed.status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": authenticated["refresh_token"]},
    ).status_code == 401
    assert login(client, "test-admin", "AdminPass123!").status_code == 401
    assert login(client, "test-admin", "NewAdminPass456!").status_code == 200


def test_role_change_invalidates_users_existing_tokens(client, session):
    user = AuthService(session).create_user(
        "role-change", "RoleChange123!", UserRole.VIEWER
    )
    authenticated = login(client, "role-change", "RoleChange123!").json()
    assert client.patch(
        f"/api/v1/users/{user.id}", json={"role": "DISPATCHER"}
    ).status_code == 200

    assert client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {authenticated['access_token']}"
        },
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": authenticated["refresh_token"]},
    ).status_code == 401
