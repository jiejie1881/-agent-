from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryPeriod,
    DeliveryPriority,
    DeliveryStopStatus,
    DispatchPlanStatus,
)
from app.schemas.auto_dispatch import DispatchVehicleResponse
from app.schemas.driver import DeliveryProofResponse, serialize_stop_utc


class DispatchPlanSummaryResponse(BaseModel):
    id: int
    delivery_date: Date
    version: int
    status: DispatchPlanStatus
    created_at: datetime
    updated_at: datetime


class PersistedDispatchOrderDetailResponse(BaseModel):
    id: int
    delivery_demand_id: int
    store_id: int
    store_code: str
    store_name: str
    store_address: str | None
    store_longitude: Decimal | None
    store_latitude: Decimal | None
    quantity: Decimal
    status: DeliveryDemandStatus
    priority: DeliveryPriority
    delivery_status: DeliveryStopStatus
    receiver_name: str | None
    receiver_phone: str | None
    signed_at: datetime | None

    @field_serializer('signed_at')
    def utc_signed_time(self,value):
        return serialize_stop_utc(value)
    driver_remark: str | None
    proofs: list[DeliveryProofResponse]


class PersistedDispatchRouteResponse(BaseModel):
    id: int
    code: str
    name: str


class PersistedDispatchOrderResponse(BaseModel):
    id: int
    actual_driver_id: int | None = None
    driver_username: str | None = None
    driver_name: str | None = None
    vehicle: DispatchVehicleResponse
    period: DeliveryPeriod
    trip_no: int
    route: PersistedDispatchRouteResponse
    total_load: Decimal
    details: list[PersistedDispatchOrderDetailResponse]


class PersistedUnassignedDemandResponse(BaseModel):
    id: int
    delivery_demand_id: int
    store_id: int
    store_code: str
    store_name: str
    store_address: str | None
    store_longitude: Decimal | None
    store_latitude: Decimal | None
    period: DeliveryPeriod
    quantity: Decimal
    reasons: list[str]
    priority: DeliveryPriority


class DispatchPlanDetailResponse(DispatchPlanSummaryResponse):
    source: Literal["TRADITIONAL", "AGENT"] = "TRADITIONAL"
    orders: list[PersistedDispatchOrderResponse]
    unassigned_demands: list[PersistedUnassignedDemandResponse]


class DispatchPlanValidationResponse(BaseModel):
    plan_id: int
    valid: bool
    issues: list[dict[str, object]]


class DispatchDemandMoveRequest(BaseModel):
    delivery_demand_id: int = Field(gt=0)
    source_order_id: int = Field(gt=0)
    target_order_id: int = Field(gt=0)
