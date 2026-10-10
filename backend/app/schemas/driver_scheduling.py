from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import TimestampSchema

Shift = Literal["MORNING", "AFTERNOON"]


class AttendanceInput(BaseModel):
    driver_id: int = Field(gt=0)
    date: date
    period: Shift
    available: bool


class ScheduleInput(BaseModel):
    date: date
    period: Shift
    vehicle_id: int = Field(gt=0)
    driver_id: int | None = Field(default=None, gt=0)


class FixedAttendanceInput(BaseModel):
    effective_date: date
    period: Shift
    available: bool


class SubstituteInput(BaseModel):
    driver_id: int = Field(gt=0)


class LeaveInput(BaseModel):
    driver_id: int = Field(gt=0)
    start_date: date
    end_date: date
    period: Literal["MORNING", "AFTERNOON", "ALL_DAY"]
    reason: str = Field(min_length=1, max_length=500)
    remark: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def check_range(self):
        if self.end_date < self.start_date or not self.reason.strip():
            raise ValueError("请假日期范围或原因无效")
        return self


class DriverUpdateInput(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class DriverCreateInput(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    display_name: str | None = Field(default=None, max_length=100)
    password: str = Field(min_length=8, max_length=200)


class DriverPasswordInput(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class DefaultVehicleInput(BaseModel):
    vehicle_id: int | None = Field(default=None, gt=0)


class ScheduleResponse(TimestampSchema):
    id: int
    date: date
    period: str
    vehicle_id: int
    driver_id: int
    original_driver_id: int | None
    kind: str
    status: str
    actor_id: int


class LeaveResponse(TimestampSchema):
    id: int
    driver_id: int
    start_date: date
    end_date: date
    period: str
    reason: str
    remark: str | None
    status: str
    actor_id: int
