from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.delivery_demand import DeliveryDemandCreate


class ParseDemandText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=6000)

    @field_validator('text')
    @classmethod
    def non_blank(cls, value):
        if not value.strip(): raise ValueError('请输入配送需求文本')
        return value


class ExtractedDemand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_text: str = Field(min_length=1, max_length=6000)
    date_text: str | None = Field(default=None, max_length=100)
    store_text: str | None = Field(default=None, max_length=100)
    period_text: str | None = Field(default=None, max_length=30)
    quantity_text: str | None = Field(default=None, max_length=30)
    unit_text: str | None = Field(default=None, max_length=20)
    priority_text: str | None = Field(default=None, max_length=30)
    remark_text: str | None = Field(default=None, max_length=500)


class ExtractedBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ExtractedDemand] = Field(min_length=1, max_length=30)


class ConfirmDemandBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    confirmed: bool
    items: list[DeliveryDemandCreate] = Field(min_length=1, max_length=30)
