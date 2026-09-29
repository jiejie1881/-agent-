from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import DeliveryPeriod


class DispatchValidationRequest(BaseModel):
    vehicle_id: int = Field(gt=0)
    delivery_demand_id: int = Field(gt=0)
    route_id: int = Field(gt=0)
    period: DeliveryPeriod
    quantity: Decimal = Field(max_digits=12, decimal_places=2)


class ConstraintValidationResponse(BaseModel):
    constraint: str
    passed: bool
    reason: str | None = None
    code: str | None = None


class DispatchValidationResponse(BaseModel):
    is_valid: bool
    result: str
    failure_reasons: list[str]
    constraints: list[ConstraintValidationResponse]
