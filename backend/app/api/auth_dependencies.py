from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.domain.enums import UserRole
from app.domain.exceptions import AuthenticationError, PermissionDeniedError
from app.domain.permissions import Permission, ROLE_PERMISSIONS, has_permission
from app.infrastructure.database.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    session: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("请先登录")
    claims = decode_access_token(
        credentials.credentials, get_settings().jwt_secret_key
    )
    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        raise AuthenticationError() from None
    user = UserRepository(session).get(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError()
    if claims.get("role") != user.role.value:
        raise AuthenticationError()
    if claims.get("ver") != user.token_version:
        raise AuthenticationError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _required_permission(request: Request) -> Permission:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return Permission.READ
    path = request.url.path
    if request.method == "POST":
        normalized_path = path.rstrip("/")
        if normalized_path.endswith("/agent/chat") or normalized_path.endswith(
            "/agent/conversations"
        ) or (
            "/agent/conversations/" in normalized_path
            and (
                normalized_path.endswith("/messages")
                or "/pending-actions/" in normalized_path
            )
        ):
            return Permission.AGENT_READ
    if any(
        segment in path
        for segment in ("/terrains", "/routes", "/stores", "/vehicle-types", "/vehicles", "/cargo-categories")
    ):
        return Permission.MASTER_DATA_WRITE
    if any(segment in path for segment in ("/vehicle-attendances", "/delivery-demands")):
        return Permission.OPERATIONS_WRITE
    if any(
        segment in path
        for segment in ("/auto-dispatch", "/dispatch-plans", "/dispatch-validations")
    ):
        return Permission.DISPATCH_WRITE
    return Permission.ADMIN_ONLY


def enforce_rbac(request: Request, current_user: CurrentUser) -> User:
    required = _required_permission(request)
    if not has_permission(current_user.role, required):
        raise PermissionDeniedError()
    return current_user


def require_admin(current_user: CurrentUser) -> User:
    if current_user.role != UserRole.ADMIN:
        raise PermissionDeniedError()
    return current_user
