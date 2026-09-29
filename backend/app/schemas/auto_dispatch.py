from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.domain.enums import DeliveryPeriod, DispatchPlanStatus, VehicleTypeCode


class AutoDispatchRequest(BaseModel):
    date: date


class DispatchVehicleResponse(BaseModel):
    id: int
    code: str
    plate_number: str
    vehicle_type_id: int
    vehicle_type_code: VehicleTypeCode
    vehicle_type_name: str


class DispatchRouteResponse(BaseModel):
    id: int
    code: str
    name: str
    terrain_id: int
    terrain_name: str


class DispatchStoreResponse(BaseModel):
    demand_id: int
    store_id: int
    store_code: str
    store_name: str
    quantity: Decimal


class DispatchTripResponse(BaseModel):
    vehicle: DispatchVehicleResponse
    period: DeliveryPeriod
    trip_no: int
    route: DispatchRouteResponse
    stores: list[DispatchStoreResponse]
    total_load: Decimal


class UnassignedDemandResponse(BaseModel):
    demand_id: int
    store_id: int
    store_code: str
    store_name: str
    period: DeliveryPeriod
    quantity: Decimal
    reasons: list[str]


class AutoDispatchResponse(BaseModel):
    plan_id: int
    date: date
    version: int
    status: DispatchPlanStatus
    trips: list[DispatchTripResponse]
    unassigned_demands: list[UnassignedDemandResponse]
