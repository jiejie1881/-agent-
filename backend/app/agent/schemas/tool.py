from __future__ import annotations

from copy import deepcopy
from datetime import date as Date
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.domain.enums import DeliveryPeriod
from app.domain.permissions import Permission
from app.schemas.common import PaginationParams


def _strict_integer_field(value: Any, info: ValidationInfo, model: type[BaseModel]) -> Any:
    annotation = model.model_fields[info.field_name].annotation
    if (annotation is int or int in get_args(annotation)) and value is not None and type(value) is not int:
        raise ValueError('整数参数必须为JSON整数，不接受布尔值、数字字符串或小数')
    return value


class StrictToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator('*', mode='before')
    @classmethod
    def require_integer_types(cls, value: Any, info: ValidationInfo) -> Any:
        return _strict_integer_field(value, info, cls)


class PaginatedToolArgs(PaginationParams):
    model_config = ConfigDict(extra="forbid")

    @field_validator('*', mode='before')
    @classmethod
    def require_integer_types(cls, value: Any, info: ValidationInfo) -> Any:
        return _strict_integer_field(value, info, cls)


class ListDeliveryDemandsArgs(PaginatedToolArgs):
    date: Date = Field(description="需要查询配送需求的日期，格式为YYYY-MM-DD")
    period: DeliveryPeriod | None = Field(
        default=None,
        description="可选配送时段，只能是MORNING或AFTERNOON",
    )
    store_id: int | None = Field(
        default=None,
        gt=0,
        description="可选门店ID，必须是正整数",
    )


class GetVehicleAttendanceArgs(StrictToolArgs):
    date: Date = Field(description="需要查询车辆出勤的日期，格式为YYYY-MM-DD")
    vehicle_id: int | None = Field(
        default=None,
        gt=0,
        description="可选车辆ID，必须是正整数",
    )


class ListDispatchPlansArgs(PaginatedToolArgs):
    delivery_date: Date = Field(
        description="需要查询派车方案的配送日期，格式为YYYY-MM-DD"
    )


class PlanIdToolArgs(StrictToolArgs):
    plan_id: int = Field(gt=0, description="派车方案ID，必须是正整数")


class GetDispatchPlanDetailArgs(PlanIdToolArgs):
    pass


class GetUnassignedDemandsArgs(PlanIdToolArgs):
    pass


class ValidateDispatchPlanArgs(PlanIdToolArgs):
    pass


class MoveDeliveryDemandArgs(PlanIdToolArgs):
    delivery_demand_id: int = Field(gt=0, description="待移动配送需求ID")
    source_order_id: int = Field(gt=0, description="当前配送任务ID")
    target_order_id: int = Field(gt=0, description="目标配送任务ID")


class CancelDispatchPlanArgs(PlanIdToolArgs):
    pass


class SearchKnowledgeBaseArgs(StrictToolArgs):
    knowledge_base_id: int | None = Field(default=None, gt=0, description="可选知识库ID；服务端按当前用户校验权限")
    query: str = Field(
        min_length=1,
        max_length=500,
        description="需要查询的物流业务规则、运输规范或操作说明",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="可选的最相关知识片段数；未传时使用服务端配置",
    )
    document_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="可选文档类型过滤，例如 cold_chain 或 dispatch_rule",
    )


class AgentToolDefinition(BaseModel):
    """Description and generated parameters for one model-visible function."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    arguments_schema: type[BaseModel] = Field(exclude=True, repr=False)
    read_only: bool = True
    requires_confirmation: bool = False
    required_permission: Permission = Permission.AGENT_READ

    @property
    def parameters(self) -> dict[str, Any]:
        schema = deepcopy(self.arguments_schema.model_json_schema())
        definitions = schema.pop("$defs", {})
        return self._inline_local_references(schema, definitions)

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @classmethod
    def _inline_local_references(
        cls, value: Any, definitions: dict[str, Any]
    ) -> Any:
        if isinstance(value, list):
            return [
                cls._inline_local_references(item, definitions) for item in value
            ]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            definition_name = reference.removeprefix("#/$defs/")
            target = definitions.get(definition_name)
            if target is not None:
                merged = deepcopy(target)
                merged.update({key: item for key, item in value.items() if key != "$ref"})
                return cls._inline_local_references(merged, definitions)
        return {
            key: cls._inline_local_references(item, definitions)
            for key, item in value.items()
        }


LIST_DELIVERY_DEMANDS_DEFINITION = AgentToolDefinition(
    name="list_delivery_demands",
    description=(
        "查询指定日期的门店配送需求，可按配送时段和门店筛选。"
        "当用户询问某天有哪些配送需求、上午或下午需求、某门店当天需求时使用；"
        "不能创建、修改或取消需求。"
    ),
    arguments_schema=ListDeliveryDemandsArgs,
)

GET_VEHICLE_ATTENDANCE_DEFINITION = AgentToolDefinition(
    name="get_vehicle_attendance",
    description=(
        "查询指定日期的车辆出勤情况，也可以限定一个车辆ID。"
        "当用户询问某天哪些车辆可出勤或某辆车当天是否出勤时使用；"
        "不能修改车辆出勤状态。"
    ),
    arguments_schema=GetVehicleAttendanceArgs,
)

LIST_DISPATCH_PLANS_DEFINITION = AgentToolDefinition(
    name="list_dispatch_plans",
    description=(
        "查询指定配送日期的派车方案版本列表。"
        "当用户询问某天有哪些V1、V2等方案及其状态时使用；"
        "不返回单个方案的完整任务明细。"
    ),
    arguments_schema=ListDispatchPlansArgs,
)

GET_DISPATCH_PLAN_DETAIL_DEFINITION = AgentToolDefinition(
    name="get_dispatch_plan_detail",
    description=(
        "根据方案ID查询派车方案详情，包括车辆任务、趟次、线路、门店需求和未分配需求。"
        "不能调整或发布方案。"
    ),
    arguments_schema=GetDispatchPlanDetailArgs,
)

GET_UNASSIGNED_DEMANDS_DEFINITION = AgentToolDefinition(
    name="get_unassigned_demands",
    description=(
        "根据方案ID查询该方案中的未分配配送需求及原因。"
        "当用户询问哪些需求未分配或未分配原因时使用；不能重新分配需求。"
    ),
    arguments_schema=GetUnassignedDemandsArgs,
)

VALIDATE_DISPATCH_PLAN_DEFINITION = AgentToolDefinition(
    name="validate_dispatch_plan",
    description=(
        "根据方案ID只读检查派车方案当前是否满足发布前业务规则，并返回全部发现的问题。"
        "该检查不会发布、修改或取消方案。"
    ),
    arguments_schema=ValidateDispatchPlanArgs,
)

MOVE_DELIVERY_DEMAND_DEFINITION = AgentToolDefinition(
    name="move_delivery_demand",
    description=(
        "申请把DRAFT派车方案中的一个配送需求从原任务移动到目标任务。"
        "必须提供方案、需求、原任务和目标任务的准确ID；只生成待确认操作，不会立即修改方案。"
    ),
    arguments_schema=MoveDeliveryDemandArgs,
    read_only=False,
    requires_confirmation=True,
    required_permission=Permission.DISPATCH_WRITE,
)

CANCEL_DISPATCH_PLAN_DEFINITION = AgentToolDefinition(
    name="cancel_dispatch_plan",
    description=(
        "申请取消指定派车方案。该操作风险较高，只生成待确认操作，不会立即取消方案。"
    ),
    arguments_schema=CancelDispatchPlanArgs,
    read_only=False,
    requires_confirmation=True,
    required_permission=Permission.DISPATCH_WRITE,
)

SEARCH_KNOWLEDGE_BASE_DEFINITION = AgentToolDefinition(
    name="search_knowledge_base",
    description=(
        "查询企业物流知识库，适用于派车规则、系统能力边界、配送操作规范、"
        "异常处理和系统操作说明。返回可核验的文档来源和章节。"
        "不得用于查询当日配送需求、车辆出勤、派车方案等实时数据。"
    ),
    arguments_schema=SearchKnowledgeBaseArgs,
)
