from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel


class ReferencePlanResponse(BaseModel):
    id: int
    version: int
    status: str
    selection: str


class UnassignedExampleResponse(BaseModel):
    demand_id: int
    store_name: str
    priority: str
    reasons: list[str]


class PendingExampleResponse(BaseModel):
    demand_id: int
    store_name: str
    priority: str
    period: str


class VehicleUnavailableExampleResponse(BaseModel):
    order_id: int
    vehicle_id: int
    vehicle_plate: str
    period: str
    trip_no: int
    attendance: str
    issues: list[str]


class FailedStopExampleResponse(BaseModel):
    stop_id: int
    order_id: int
    demand_id: int
    store_name: str
    vehicle_plate: str
    current_driver_username: str | None
    arrived_at: datetime | None
    failure_reason: str | None


ExampleType = TypeVar("ExampleType")


class ExampleSectionResponse(BaseModel, Generic[ExampleType]):
    count: int
    examples: list[ExampleType]
    truncated: bool


class DailyExceptionReportResponse(BaseModel):
    delivery_date: date
    reference_plan: ReferencePlanResponse | None
    plan_unassigned: ExampleSectionResponse[UnassignedExampleResponse]
    pending_outside_reference_plan: ExampleSectionResponse[PendingExampleResponse]
    plan_vehicle_unavailable: ExampleSectionResponse[VehicleUnavailableExampleResponse]
    failed_stops: ExampleSectionResponse[FailedStopExampleResponse]
    notices: list[str]
    note: str
