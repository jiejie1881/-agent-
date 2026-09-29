from enum import Enum

from app.domain.enums import UserRole


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


def has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
