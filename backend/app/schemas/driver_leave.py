from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class LeaveRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    start_date: date
    end_date: date
    period: Literal["MORNING", "AFTERNOON", "ALL_DAY"]
    leave_type: str = Field(default="OTHER", min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        return self


class LeaveReviewInput(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    review_remark: str | None = Field(default=None, max_length=1000)


class SubstitutionInput(BaseModel):
    leave_request_id: int | None = Field(default=None, gt=0)
    vehicle_id: int = Field(gt=0)
    substitute_driver_id: int = Field(gt=0)
    date: date
    period: Literal["MORNING", "AFTERNOON"]
