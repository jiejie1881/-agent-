from pydantic import BaseModel, Field, field_validator

from app.schemas.common import TimestampSchema
from app.schemas.route import RouteResponse


class StoreBase(BaseModel):
    code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    address: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=30)
    is_active: bool = True

    @field_validator("code", "name", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value.strip() if isinstance(value, str) else value

    @field_validator("is_active", mode="before")
    @classmethod
    def reject_null_boolean(cls, value: object) -> object:
        if value is None:
            raise ValueError("启用状态不能为 null")
        return value

    @field_validator("address", "contact_name", "contact_phone", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class StoreCreate(StoreBase):
    pass


class StoreUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    address: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None

    @field_validator("code", "name", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value.strip() if isinstance(value, str) else value

    @field_validator("is_active", mode="before")
    @classmethod
    def reject_null_boolean(cls, value: object) -> object:
        if value is None:
            raise ValueError("启用状态不能为 null")
        return value


class StoreResponse(StoreBase, TimestampSchema):
    id: int


class StoreRouteCreate(BaseModel):
    route_id: int = Field(gt=0)


class StoreRouteResponse(TimestampSchema):
    id: int
    store_id: int
    route_id: int
    route: RouteResponse
