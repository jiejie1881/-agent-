from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.domain.enums import DeliveryPeriod
from app.domain.enums import VehicleTypeCode


@dataclass(frozen=True)
class EngineDemand:
    id: int
    date: date
    store_id: int
    store_code: str
    store_name: str
    period: DeliveryPeriod
    quantity: Decimal


@dataclass(frozen=True)
class EngineVehicle:
    id: int
    code: str
    plate_number: str
    vehicle_type_id: int
    vehicle_type_code: VehicleTypeCode
    vehicle_type_name: str
    min_load: Decimal
    max_load: Decimal


@dataclass(frozen=True)
class EngineRoute:
    id: int
    code: str
    name: str
    terrain_id: int
    terrain_name: str


@dataclass(frozen=True)
class CandidateOption:
    demand_id: int
    vehicle_id: int
    route_id: int


@dataclass
class CandidateBuildResult:
    options: list[CandidateOption] = field(default_factory=list)
    failure_reasons: dict[int, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class LoadedDemand:
    demand: EngineDemand
    quantity: Decimal


@dataclass(frozen=True)
class TripPlan:
    vehicle: EngineVehicle
    period: DeliveryPeriod
    trip_no: int
    route: EngineRoute
    demands: tuple[LoadedDemand, ...]
    total_load: Decimal


@dataclass(frozen=True)
class UnassignedDemand:
    demand: EngineDemand
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DispatchEngineResult:
    dispatch_date: date
    trips: tuple[TripPlan, ...]
    unassigned_demands: tuple[UnassignedDemand, ...]


@dataclass(frozen=True)
class DispatchEngineInput:
    dispatch_date: date
    demands: tuple[EngineDemand, ...]
    vehicles: tuple[EngineVehicle, ...]
    routes: dict[int, EngineRoute]
    store_route_ids: dict[int, set[int]]
    permissions: set[tuple[int, int]]
