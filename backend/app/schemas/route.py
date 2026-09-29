from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import TimestampSchema
from app.schemas.terrain import TerrainResponse


class RouteBase(BaseModel):
    code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
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


class RouteCreate(RouteBase):
    pass


class RouteUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
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


class RouteResponse(RouteBase, TimestampSchema):
    id: int


class RouteTerrainCreate(BaseModel):
    terrain_id: int = Field(gt=0)
    effective_date: date


class RouteTerrainUpdate(BaseModel):
    terrain_id: int | None = Field(default=None, gt=0)
    effective_date: date | None = None

    @field_validator("terrain_id", "effective_date", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value


class RouteTerrainResponse(TimestampSchema):
    id: int
    route_id: int
    terrain_id: int
    effective_date: date
    terrain: TerrainResponse
