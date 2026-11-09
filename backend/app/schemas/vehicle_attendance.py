from __future__ import annotations

from datetime import date as Date

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import TimestampSchema
from app.schemas.vehicle import VehicleResponse


class VehicleAttendanceBase(BaseModel):
    date: Date
    vehicle_id: int = Field(gt=0)
    available: bool


class VehicleAttendanceCreate(VehicleAttendanceBase):
    pass


class VehicleAttendanceUpdate(BaseModel):
    date: Date | None = None
    vehicle_id: int | None = Field(default=None, gt=0)
    available: bool | None = None

    @field_validator("date", "vehicle_id", "available", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("字段不能为 null")
        return value


class VehicleAttendanceResponse(VehicleAttendanceBase, TimestampSchema):
    id: int
    vehicle: VehicleResponse
