from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field


class CompareReports(BaseModel):
    model_config = ConfigDict(extra='forbid')
    report_ids: list[Annotated[int, Field(gt=0)]] = Field(min_length=2, max_length=5)
