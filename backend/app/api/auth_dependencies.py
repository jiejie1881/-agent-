from enum import Enum
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.domain.enums import UserRole
from app.domain.exceptions import AuthenticationError, PermissionDeniedError
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


class Permission(str, Enum):
    READ = "READ"
    AGENT_READ = "AGENT_READ"
    MASTER_DATA_WRITE = "MASTER_DATA_WRITE"
    OPERATIONS_WRITE = "OPERATIONS_WRITE"
    DISPATCH_WRITE = "DISPATCH_WRITE"
    ADMIN_ONLY = "ADMIN_ONLY"


ROLE_PERMISSIONS = {
    UserRole.ADMIN: set(Permission),
    UserRole.DISPATCHER: {
        Permission.READ,
        Permission.AGENT_READ,
        Permission.OPERATIONS_WRITE,
        Permission.DISPATCH_WRITE,
    },
    UserRole.VIEWER: {Permission.READ, Permission.AGENT_READ},
}


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
            and normalized_path.endswith("/messages")
        ):
            return Permission.AGENT_READ
    if any(
        segment in path
        for segment in ("/terrains", "/routes", "/stores", "/vehicle-types", "/vehicles")
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
    if required not in ROLE_PERMISSIONS[current_user.role]:
        raise PermissionDeniedError()
    return current_user


def require_admin(current_user: CurrentUser) -> User:
    if current_user.role != UserRole.ADMIN:
        raise PermissionDeniedError()
    return current_user
