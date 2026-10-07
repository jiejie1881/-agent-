from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.domain.enums import DeliveryPeriod


@dataclass(frozen=True)
class DispatchValidationContext:
    dispatch_date: date
    vehicle_name: str
    vehicle_type_name: str
    demand_period: DeliveryPeriod
    dispatch_period: DeliveryPeriod
    quantity: Decimal
    min_load: Decimal
    max_load: Decimal
    attendance_exists: bool
    vehicle_available: bool
    store_belongs_to_route: bool
    terrain_configured: bool
    terrain_name: str | None
    terrain_allowed: bool
    cargo_category_id: int | None = None
    cargo_category_name: str | None = None
    cargo_capability_exists: bool = True
    cargo_allowed: bool = True
    requires_temperature_control: bool = False
    demand_min_temperature: Decimal | None = None
    demand_max_temperature: Decimal | None = None
    vehicle_min_temperature: Decimal | None = None
    vehicle_max_temperature: Decimal | None = None


@dataclass(frozen=True)
class ConstraintResult:
    constraint: str
    passed: bool
    reason: str | None = None
    code: str | None = None


class DispatchConstraint(Protocol):
    name: str

    def validate(self, context: DispatchValidationContext) -> ConstraintResult: ...
