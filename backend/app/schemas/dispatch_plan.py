from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryPeriod,
    DispatchPlanStatus,
)
from app.schemas.auto_dispatch import DispatchVehicleResponse


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
    quantity: Decimal
    status: DeliveryDemandStatus


class PersistedDispatchRouteResponse(BaseModel):
    id: int
    code: str
    name: str


class PersistedDispatchOrderResponse(BaseModel):
    id: int
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
    period: DeliveryPeriod
    quantity: Decimal
    reasons: list[str]


class DispatchPlanDetailResponse(DispatchPlanSummaryResponse):
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
