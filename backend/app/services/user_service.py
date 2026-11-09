from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.domain.exceptions import ConflictError, NotFoundError
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import UserCreate, UserUpdate
from app.services.audit_log_service import AuditAction, AuditLogService


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = UserRepository(session)

    def list(self, offset: int, limit: int) -> list[User]:
        return self.repository.list(offset, limit)

    def create(self, data: UserCreate, actor: User) -> User:
        if self.repository.get_by_username(data.username.strip()):
            raise ConflictError("用户名已存在")
        user = User(
            username=data.username.strip(),
            password_hash=hash_password(data.password),
            role=data.role,
            is_active=data.is_active,
        )
        def action() -> User:
            created = self.repository.add(user)
            AuditLogService(self.session).add(
                actor,
                AuditAction.USER_CREATED,
                "User",
                created.id,
                {
                    "username": created.username,
                    "role": created.role.value,
                    "is_active": created.is_active,
                },
            )
            return created

        return self._commit(action)

    def update(self, user_id: int, data: UserUpdate, actor: User) -> User:
        user = self.repository.get(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        updates = data.model_dump(exclude_unset=True)
        if user.id == actor.id and "role" in updates and updates["role"] != user.role:
            raise ConflictError("不能修改自己的角色")
        if user.id == actor.id and updates.get("is_active") is False:
            raise ConflictError("不能禁用当前登录用户")
        if "username" in updates:
            updates["username"] = updates["username"].strip()
        before = {
            field: (
                getattr(user, field).value
                if field == "role"
                else getattr(user, field)
            )
            for field in updates
        }
        security_changed = any(
            field in updates and updates[field] != getattr(user, field)
            for field in ("role", "is_active")
        )
        for field, value in updates.items():
            setattr(user, field, value)
        if security_changed:
            user.token_version += 1
        def action() -> User:
            updated = self.repository.add(user)
            after = {
                field: (
                    getattr(updated, field).value
                    if field == "role"
                    else getattr(updated, field)
                )
                for field in updates
            }
            AuditLogService(self.session).add(
                actor,
                AuditAction.USER_UPDATED,
                "User",
                updated.id,
                {"before": before, "after": after},
            )
            return updated

        return self._commit(action)

    def _commit(self, action):
        try:
            result = action()
            self.session.commit()
            return result
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("用户名已存在") from exc
