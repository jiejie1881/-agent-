from __future__ import annotations

from datetime import date as Date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import DeliveryDemandStatus, DeliveryPeriod, DeliveryPriority
from app.schemas.cargo_category import CargoCategoryResponse
from app.schemas.common import TimestampSchema
from app.schemas.store import StoreResponse


class DeliveryDemandBase(BaseModel):
    date: Date
    store_id: int = Field(gt=0)
    period: DeliveryPeriod
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    cargo_category_id: int | None = Field(default=None, gt=0)
    priority: DeliveryPriority = DeliveryPriority.NORMAL
    requires_temperature_control: bool = False
    min_temperature: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    max_temperature: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    status: DeliveryDemandStatus

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @model_validator(mode="after")
    def validate_temperature_range(self):
        if self.requires_temperature_control:
            if self.min_temperature is None or self.max_temperature is None:
                raise ValueError("温控需求必须填写最低温度和最高温度")
        if (
            self.min_temperature is not None
            and self.max_temperature is not None
            and self.min_temperature > self.max_temperature
        ):
            raise ValueError("最低温度不能大于最高温度")
        return self


class DeliveryDemandCreate(DeliveryDemandBase):
    status: DeliveryDemandStatus = DeliveryDemandStatus.PENDING


class DeliveryDemandUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: Date | None = None
    store_id: int | None = Field(default=None, gt=0)
    period: DeliveryPeriod | None = None
    quantity: Decimal | None = Field(
        default=None, gt=0, max_digits=12, decimal_places=2
    )
    cargo_category_id: int | None = Field(default=None, gt=0)
    priority: DeliveryPriority | None = None
    requires_temperature_control: bool | None = None
    min_temperature: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    max_temperature: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)

    @field_validator(
        "date", "store_id", "period", "quantity", "cargo_category_id",
        "priority", "requires_temperature_control", mode="before"
    )
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value

    @model_validator(mode="after")
    def validate_explicit_temperature_range(self):
        if self.requires_temperature_control is True:
            if self.min_temperature is None or self.max_temperature is None:
                raise ValueError("开启温控时必须同时填写最低温度和最高温度")
        if (
            self.min_temperature is not None
            and self.max_temperature is not None
            and self.min_temperature > self.max_temperature
        ):
            raise ValueError("最低温度不能大于最高温度")
        return self

class DeliveryDemandResponse(DeliveryDemandBase, TimestampSchema):
    id: int
    core_fields_editable: bool
    store: StoreResponse
    cargo_category: CargoCategoryResponse
