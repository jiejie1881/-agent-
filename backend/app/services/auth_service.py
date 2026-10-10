from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.domain.enums import UserRole
from app.domain.exceptions import AuthenticationError, BusinessError, ConflictError
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse, UserResponse
from app.services.audit_log_service import AuditAction, AuditLogService


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = UserRepository(session)

    def login(self, username: str, password: str) -> TokenResponse:
        return self._login(username, password)

    def login_driver(self, username: str, password: str) -> TokenResponse:
        return self._login(username, password, required_role=UserRole.DRIVER)

    def _login(
        self,
        username: str,
        password: str,
        required_role: UserRole | None = None,
    ) -> TokenResponse:
        user = self.repository.get_by_username(username.strip())
        if user is None or not user.is_active or not verify_password(
            password, user.password_hash
        ):
            raise AuthenticationError("用户名或密码错误")
        if required_role is not None and user.role != required_role:
            raise AuthenticationError("用户名或密码错误")
        # 代班司机可没有默认车辆；任务授权依据实际排班与任务快照。
        tokens = self._tokens_for(user)
        AuditLogService(self.session).add(
            user,
            AuditAction.LOGIN,
            "User",
            user.id,
            {"role": user.role.value},
        )
        self.session.commit()
        return tokens

    def refresh(self, refresh_token: str) -> TokenResponse:
        settings = get_settings()
        claims = decode_refresh_token(refresh_token, settings.jwt_secret_key)
        try:
            user = self.repository.get(int(claims["sub"]))
        except (KeyError, TypeError, ValueError):
            raise AuthenticationError() from None
        if user is None or not user.is_active:
            raise AuthenticationError()
        if claims.get("role") != user.role.value or claims.get("ver") != user.token_version:
            raise AuthenticationError("Refresh Token已失效")
        return self._tokens_for(user)

    @staticmethod
    def _tokens_for(user: User) -> TokenResponse:
        settings = get_settings()
        return TokenResponse(
            access_token=create_access_token(
                str(user.id),
                user.role.value,
                user.token_version,
                settings.jwt_secret_key,
                settings.jwt_access_token_expire_minutes,
            ),
            refresh_token=create_refresh_token(
                str(user.id),
                user.role.value,
                user.token_version,
                settings.jwt_secret_key,
                settings.jwt_refresh_token_expire_days,
            ),
            user=UserResponse.model_validate(user),
        )

    def create_user(self, username: str, password: str, role: UserRole) -> User:
        try:
            user = User(
                username=username.strip(),
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
            self.repository.add(user)
            self.session.commit()
            return user
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("用户名已存在") from exc

    def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.password_hash):
            raise AuthenticationError("当前密码错误")
        user.password_hash = hash_password(new_password)
        user.token_version += 1
        self.session.add(user)
        AuditLogService(self.session).add(
            user,
            AuditAction.PASSWORD_CHANGED,
            "User",
            user.id,
            {"password_changed": True},
        )
        self.session.commit()
