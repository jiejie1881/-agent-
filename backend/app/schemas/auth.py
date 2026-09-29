from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import UserRole


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: UserRole
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    role: UserRole
    is_active: bool = True

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("用户名不能为空")
        return value.strip()


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=100)
    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("用户名不能为空")
        return value.strip()

    @field_validator("role", "is_active", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为null")
        return value
