from enum import Enum

from app.domain.enums import UserRole


class Permission(str, Enum):
    READ = "READ"
    AGENT_READ = "AGENT_READ"
    MASTER_DATA_WRITE = "MASTER_DATA_WRITE"
    OPERATIONS_WRITE = "OPERATIONS_WRITE"
    DISPATCH_WRITE = "DISPATCH_WRITE"
    AGENT_DRAFT_ACCEPT = "AGENT_DRAFT_ACCEPT"
    AGENT_PLAN_PUBLISH = "AGENT_PLAN_PUBLISH"
    ADMIN_ONLY = "ADMIN_ONLY"


ROLE_PERMISSIONS = {
    UserRole.ADMIN: set(Permission) - {Permission.AGENT_DRAFT_ACCEPT, Permission.AGENT_PLAN_PUBLISH},
    UserRole.DISPATCHER: {
        Permission.READ,
        Permission.AGENT_READ,
        Permission.OPERATIONS_WRITE,
        Permission.DISPATCH_WRITE,
    },
    UserRole.VIEWER: {Permission.READ, Permission.AGENT_READ},
    # Drivers use the isolated /api/driver surface. They must not inherit
    # management-console read access simply because they have a valid JWT.
    UserRole.DRIVER: set(),
}


def has_permission(role: UserRole, permission: Permission) -> bool:
    if permission == Permission.AGENT_DRAFT_ACCEPT:
        from app.core.config import get_settings

        settings=get_settings()
        return (role == UserRole.ADMIN and settings.agent_draft_accept_admin_enabled) or (role == UserRole.DISPATCHER and settings.agent_draft_accept_dispatcher_enabled)
    if permission == Permission.AGENT_PLAN_PUBLISH:
        from app.core.config import get_settings

        settings = get_settings()
        return settings.agent_plan_publish_enabled and ((role == UserRole.ADMIN and settings.agent_plan_publish_admin_enabled) or
            (role == UserRole.DISPATCHER and settings.agent_plan_publish_dispatcher_enabled))
    return permission in ROLE_PERMISSIONS[role]
