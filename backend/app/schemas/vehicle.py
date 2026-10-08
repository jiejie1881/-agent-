from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import VehicleTypeCode
from app.schemas.common import TimestampSchema
from app.schemas.terrain import TerrainResponse
from app.schemas.cargo_category import CargoCategoryResponse


class VehicleTypeBase(BaseModel):
    code: VehicleTypeCode
    name: str = Field(min_length=1, max_length=100)
    min_load: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    max_load: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    is_active: bool = True

    @field_validator("code", "name", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value.strip() if isinstance(value, str) else value

    @field_validator("min_load", "max_load", "is_active", mode="before")
    @classmethod
    def reject_null_values(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value

    @model_validator(mode="after")
    def validate_load_range(self):
        if self.min_load > self.max_load:
            raise ValueError("最低载重量不能大于最高载重量")
        return self


class VehicleTypeCreate(VehicleTypeBase):
    pass


class VehicleTypeUpdate(BaseModel):
    code: VehicleTypeCode | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    min_load: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    max_load: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    is_active: bool | None = None

    @field_validator("code", "name", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value.strip() if isinstance(value, str) else value

    @field_validator("min_load", "max_load", "is_active", mode="before")
    @classmethod
    def reject_null_values(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value


class VehicleTypeResponse(VehicleTypeBase, TimestampSchema):
    id: int


class VehicleBase(BaseModel):
    code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    plate_number: str = Field(min_length=1, max_length=20)
    vehicle_type_id: int = Field(gt=0)
    driver_user_id: int | None = Field(default=None, gt=0)
    is_active: bool = True

    @field_validator("code", "plate_number", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("vehicle_type_id", "is_active", mode="before")
    @classmethod
    def reject_null_values(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    plate_number: str | None = Field(default=None, min_length=1, max_length=20)
    vehicle_type_id: int | None = Field(default=None, gt=0)
    driver_user_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None

    @field_validator("code", "plate_number", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("vehicle_type_id", "is_active", mode="before")
    @classmethod
    def reject_null_values(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value


class VehicleResponse(VehicleBase, TimestampSchema):
    id: int
    vehicle_type: VehicleTypeResponse


class VehicleTypeTerrainPermissionCreate(BaseModel):
    terrain_id: int = Field(gt=0)


class VehicleTypeTerrainPermissionResponse(TimestampSchema):
    id: int
    vehicle_type_id: int
    terrain_id: int
    terrain: TerrainResponse


class VehicleTypeCargoCapabilityInput(BaseModel):
    cargo_category_id: int = Field(gt=0)
    is_allowed: bool = True
    min_temperature: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    max_temperature: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)

    @model_validator(mode="after")
    def validate_temperature_range(self):
        if (self.min_temperature is None) != (self.max_temperature is None):
            raise ValueError("车型温控最低温度和最高温度必须同时填写")
        if (
            self.min_temperature is not None
            and self.max_temperature is not None
            and self.min_temperature > self.max_temperature
        ):
            raise ValueError("车型温控最低温度不能大于最高温度")
        return self


class VehicleTypeCargoCapabilityReplace(BaseModel):
    capabilities: list[VehicleTypeCargoCapabilityInput]

    @model_validator(mode="after")
    def validate_unique_categories(self):
        ids = [item.cargo_category_id for item in self.capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("同一货物分类不能重复配置")
        return self


class VehicleTypeCargoCapabilityResponse(TimestampSchema):
    id: int
    vehicle_type_id: int
    cargo_category_id: int
    is_allowed: bool
    min_temperature: Decimal | None
    max_temperature: Decimal | None
    cargo_category: CargoCategoryResponse
