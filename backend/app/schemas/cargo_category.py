from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import TimestampSchema


class CargoCategoryBase(BaseModel):
    code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value


class CargoCategoryCreate(CargoCategoryBase):
    pass


class CargoCategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None

    @field_validator("code", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("name", "is_active", mode="before")
    @classmethod
    def reject_null_without_uppercase(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value.strip() if isinstance(value, str) else value


class CargoCategoryResponse(CargoCategoryBase, TimestampSchema):
    id: int
