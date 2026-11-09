from __future__ import annotations

from datetime import date as Date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import DeliveryDemandStatus, DeliveryPeriod, DeliveryPriority
from app.schemas.common import TimestampSchema
from app.schemas.store import StoreResponse


class DeliveryDemandBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: Date
    store_id: int = Field(gt=0)
    period: DeliveryPeriod
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    priority: DeliveryPriority = DeliveryPriority.NORMAL
    status: DeliveryDemandStatus

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value



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
    priority: DeliveryPriority | None = None

    @field_validator(
        "date", "store_id", "period", "quantity", "priority", mode="before"
    )
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value


class DeliveryDemandResponse(DeliveryDemandBase, TimestampSchema):
    id: int
    core_fields_editable: bool
    store: StoreResponse
