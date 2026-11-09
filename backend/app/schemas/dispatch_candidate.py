"""Non-persistent planning contracts; model-supplied IDs remain untrusted."""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from app.domain.enums import DeliveryDemandStatus, DeliveryPeriod, DeliveryPriority

POLICY_VERSION = "dispatch-context-v2"
CandidateId = Annotated[int, Field(strict=True, gt=0)]


class PlanningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class ContextDemand(PlanningModel):
    id: PositiveInt
    store_id: PositiveInt
    date: date
    period: DeliveryPeriod
    quantity: Decimal = Field(gt=0, allow_inf_nan=False)
    priority: DeliveryPriority
    status: DeliveryDemandStatus
    schedulable: bool


class ContextStore(PlanningModel):
    id: PositiveInt
    code: str
    name: str
    route_ids: tuple[PositiveInt, ...]
    is_active: bool = True


class ContextRoute(PlanningModel):
    id: PositiveInt
    code: str
    name: str
    terrain_id: PositiveInt | None
    terrain_name: str | None = None
    is_active: bool = True


class ContextVehicle(PlanningModel):
    id: PositiveInt
    code: str
    plate_number: str
    vehicle_type_id: PositiveInt
    vehicle_type_code: str
    vehicle_type_name: str
    min_load: Decimal
    max_load: Decimal
    is_active: bool
    type_active: bool
    attendance_exists: bool
    available: bool
    default_driver_id: PositiveInt | None
    operating_status: str = 'ACTIVE'
    allowed_route_ids: tuple[PositiveInt, ...] | None = None
    daily_trip_limit: PositiveInt | None = None


class ContextShift(PlanningModel):
    vehicle_id: PositiveInt
    period: DeliveryPeriod
    driver_id: PositiveInt | None
    available: bool
    violation_code: str | None = None
    message: str | None = None


class DispatchContext(PlanningModel):
    delivery_date: date
    policy_version: str = POLICY_VERSION
    snapshot_version: str
    captured_at: datetime
    demands: tuple[ContextDemand, ...]
    stores: tuple[ContextStore, ...]
    vehicles: tuple[ContextVehicle, ...]
    routes: tuple[ContextRoute, ...]
    shifts: tuple[ContextShift, ...]
    terrain_permissions: tuple[tuple[int, int], ...]
    # Whitelisted business facts include attendance, leaves, substitutions,
    # plans and task occupancy. No credentials, contact details or leave reasons.
    resource_records: dict[str, list[dict[str, Any]]]
    daily_trip_limit: int | None = None
    whole_demands_only: bool = True
    multiple_trips_per_period: bool = True

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"snapshot_version", "captured_at"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode()).hexdigest()


class CandidateTrip(PlanningModel):
    vehicle_id: CandidateId
    driver_id: CandidateId
    period: DeliveryPeriod
    trip_no: CandidateId
    route_id: CandidateId
    demand_ids: tuple[CandidateId, ...] = Field(min_length=1, max_length=10000)


class CandidateUnassigned(PlanningModel):
    demand_id: CandidateId
    explanation: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class DispatchCandidate(PlanningModel):
    candidate_id: str = Field(min_length=1, max_length=100, pattern=r"\S")
    delivery_date: date
    snapshot_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    trips: tuple[CandidateTrip, ...] = Field(default=(), max_length=10000)
    unassigned: tuple[CandidateUnassigned, ...] = Field(default=(), max_length=10000)
    planning_explanation: str = Field(default="", max_length=4000)


class CandidateViolation(PlanningModel):
    violation_code: str
    message: str
    related_ids: dict[str, int | str]


class CandidateValidationResult(PlanningModel):
    is_valid: bool
    violations: tuple[CandidateViolation, ...]
    snapshot_version: str
    assigned_count: int
    unassigned_count: int
    trip_loads: tuple[Decimal, ...]
    freshness_checked: bool = False
