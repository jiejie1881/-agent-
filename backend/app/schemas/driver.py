from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import (
    DeliveryFailureReason,
    DeliveryPeriod,
    DeliveryPriority,
    DeliveryStopStatus,
    DeliveryProofReviewStatus,
    DriverTaskStatus,
)


class DriverVehicleResponse(BaseModel):
    id: int
    code: str
    plate_number: str
    vehicle_type_code: str
    vehicle_type_name: str


class DriverProfileResponse(BaseModel):
    user_id: int
    username: str
    display_name: str | None = None
    vehicle: DriverVehicleResponse | None
    today_schedules: list[dict[str, object]] = Field(default_factory=list)


class DriverRouteResponse(BaseModel):
    id: int
    code: str
    name: str


class DriverTaskSummaryResponse(BaseModel):
    id: int
    delivery_date: date
    plan_id: int
    plan_version: int
    period: DeliveryPeriod
    trip_no: int
    route: DriverRouteResponse
    total_load: Decimal
    status: DriverTaskStatus
    stop_count: int
    highest_priority: DeliveryPriority


class DriverTaskStopResponse(BaseModel):
    id: int
    sequence: int
    delivery_demand_id: int
    store_id: int
    store_code: str
    store_name: str
    address: str | None
    contact_name: str | None
    contact_phone: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    quantity: Decimal
    priority: DeliveryPriority
    delivery_status: DeliveryStopStatus
    arrived_at: datetime | None
    signed_at: datetime | None
    receiver_name: str | None
    receiver_phone: str | None
    failure_reason: DeliveryFailureReason | None
    driver_remark: str | None
    proofs: list["DeliveryProofResponse"]


class DeliveryProofReviewResponse(BaseModel):
    id: int
    reviewer_username: str
    decision: DeliveryProofReviewStatus
    reason: str | None
    created_at: datetime


class DeliveryProofReviewRequest(BaseModel):
    decision: DeliveryProofReviewStatus
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def check_decision(self):
        self.reason = self.reason.strip() if self.reason else None
        if self.decision == DeliveryProofReviewStatus.PENDING:
            raise ValueError("审核结果只能为通过或驳回")
        if self.decision == DeliveryProofReviewStatus.REJECTED and not self.reason:
            raise ValueError("驳回回单必须填写原因")
        return self


class DeliveryProofResponse(BaseModel):
    id: int
    url: str
    content_type: str
    size_bytes: int
    created_at: datetime
    review_status: DeliveryProofReviewStatus
    replaces_proof_id: int | None
    reviews: list[DeliveryProofReviewResponse]


class DeliveryStopSignRequest(BaseModel):
    receiver_name: str = Field(min_length=1, max_length=100)
    receiver_phone: str | None = Field(default=None, max_length=30)
    remark: str | None = Field(default=None, max_length=1000)

    @field_validator("receiver_name", mode="before")
    @classmethod
    def normalize_receiver_name(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("签收人姓名不能为空")
        return value.strip()

    @field_validator("receiver_phone", "remark", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) and value.strip() else None


class DeliveryStopFailRequest(BaseModel):
    failure_reason: DeliveryFailureReason
    remark: str | None = Field(default=None, max_length=1000)

    @field_validator("remark", mode="before")
    @classmethod
    def normalize_remark(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @model_validator(mode="after")
    def require_other_reason_remark(self):
        if self.failure_reason == DeliveryFailureReason.OTHER and not self.remark:
            raise ValueError("失败原因为OTHER时必须填写备注")
        return self


class DriverTaskDetailResponse(DriverTaskSummaryResponse):
    vehicle: DriverVehicleResponse
    stops: list[DriverTaskStopResponse]


class DriverTaskPageResponse(BaseModel):
    items: list[DriverTaskSummaryResponse]
    total: int
    page: int
    page_size: int


class DriverActionResponse(BaseModel):
    task: DriverTaskDetailResponse
    operated_at: datetime
