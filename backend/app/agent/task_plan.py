"""Bounded plan contracts and server routing. No database, RAG or model calls."""
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.agent.exceptions import AgentModelResponseError
from app.domain.exceptions import PermissionDeniedError
from app.domain.permissions import has_permission


class Intent(str, Enum):
    VEHICLES = 'VEHICLES'
    DRIVERS = 'DRIVERS'
    DEMANDS = 'DEMANDS'
    TRANSPORT = 'TRANSPORT'
    ATTENDANCE = 'ATTENDANCE'
    CAPACITY = 'CAPACITY'
    DISPATCH = 'DISPATCH'
    EXCEPTIONS = 'EXCEPTIONS'
    KNOWLEDGE = 'KNOWLEDGE'
    COMPOSITE = 'COMPOSITE'
    WRITE = 'WRITE'
    CLARIFY = 'CLARIFY'


ROUTES = {
    Intent.VEHICLES: {'list_vehicles'},
    Intent.DRIVERS: {'list_drivers'},
    Intent.DEMANDS: {'list_delivery_demands'},
    Intent.TRANSPORT: {'list_transport_tasks','list_dispatch_plans','get_dispatch_plan_detail','validate_dispatch_plan'},
    Intent.ATTENDANCE: {'get_vehicle_attendance','list_drivers'},
    Intent.CAPACITY: {'list_delivery_demands','get_vehicle_attendance','list_drivers','analyze_capacity'},
    Intent.DISPATCH: {'list_delivery_demands','list_vehicles','get_vehicle_attendance','list_drivers',
                     'analyze_capacity','preview_dispatch_candidate','list_dispatch_plans',
                     'get_dispatch_plan_detail','validate_dispatch_plan','get_unassigned_demands'},
    Intent.EXCEPTIONS: {'get_daily_exceptions','list_exception_cases','list_delivery_demands','list_transport_tasks',
                       'get_dispatch_plan_detail','get_unassigned_demands','search_knowledge_base'},
    Intent.KNOWLEDGE: {'search_knowledge_base'},
    Intent.WRITE: {'list_dispatch_plans','get_dispatch_plan_detail','validate_dispatch_plan',
                  'move_delivery_demand','cancel_dispatch_plan'},
}


def route_intent(text):
    """Conservative, explainable route hints; model still must validate every plan.

    This is not a claim of general NLP classification accuracy. Ambiguous short
    follow-ups receive the composite read catalogue and their owned history.
    """
    groups = [
        (Intent.VEHICLES, ('车辆','车子','车型')),
        (Intent.DRIVERS, ('司机','代班','请假')),
        (Intent.DEMANDS, ('需求','订单','货量')),
        (Intent.TRANSPORT, ('运输任务','配送任务','方案详情')),
        (Intent.ATTENDANCE, ('出勤','考勤')),
        (Intent.CAPACITY, ('运力','载重','装载','容量')),
        (Intent.DISPATCH, ('调度','派车','候选方案','安排配送','生成方案','方案校验','能否发布')),
        (Intent.EXCEPTIONS, ('异常','失败原因','未分配','工单')),
        (Intent.KNOWLEDGE, ('知识','规则','制度','操作手册','规范')),
    ]
    found = [intent for intent,words in groups if any(w in text for w in words)]
    # A dispatch-plan detail is one object, not two independent requests.
    # Explicit transport/delivery tasks still retain their own route.
    if (Intent.DISPATCH in found and Intent.TRANSPORT in found and
            any(term in text for term in ('调度方案详情', '派车方案详情')) and
            not any(term in text for term in ('运输任务', '配送任务'))):
        found.remove(Intent.TRANSPORT)
    if any(w in text for w in ('取消方案','取消派车','移动需求','修改方案','发布方案','创建草稿')):
        found.append(Intent.WRITE)
    found=list(dict.fromkeys(found))
    route = found[0] if len(found)==1 else Intent.COMPOSITE if found else Intent.CLARIFY
    tools=set().union(*(ROUTES[i] for i in found)) if found else set().union(*(v for k,v in ROUTES.items() if k!=Intent.WRITE))
    # An unsupported publish/create request must never be "helpfully" converted
    # into cancelling/moving business data, even though HITL also exists.
    tools-={'cancel_dispatch_plan','move_delivery_demand'}
    if any(w in text for w in ('取消方案','取消派车')):tools.add('cancel_dispatch_plan')
    if any(w in text for w in ('移动需求','修改方案')):tools.add('move_delivery_demand')
    return route, found, tools


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class ResultRef(Contract):
    step_id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,31}$')
    path: tuple[str | int, ...] = Field(min_length=1,max_length=8)


class StepCondition(Contract):
    source: ResultRef
    operator: Literal['nonempty','equals'] = 'nonempty'
    value: str | int | bool | None = None


class TaskStep(Contract):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,31}$')
    tool: str = Field(min_length=1,max_length=80)
    arguments: dict[str,Any] = Field(default_factory=dict)
    depends_on: tuple[str,...] = ()
    bindings: dict[str,ResultRef] = Field(default_factory=dict)
    when: StepCondition | None = None
    expected_output: Literal['registered_tool_result'] = 'registered_tool_result'


class TaskPlan(Contract):
    # Mirror validate_plan's existing XOR rule in the schema shown to the LLM.
    # An empty steps/null clarification object must never be advertised as valid.
    model_config = ConfigDict(extra='forbid', frozen=True, json_schema_extra={
        'oneOf': [
            {'properties': {'steps': {'minItems': 1}, 'clarification': {'type': 'null'}}, 'required': ['steps']},
            {'properties': {'steps': {'maxItems': 0}, 'clarification': {'type': 'string', 'minLength': 1}}, 'required': ['clarification']},
        ]
    })
    steps: tuple[TaskStep,...] = Field(default=(),max_length=20)
    clarification: str | None = Field(default=None,max_length=1000)


def validate_plan(plan, registry, actor, allowed, limit):
    if bool(plan.steps)==bool(plan.clarification):
        raise AgentModelResponseError('计划必须包含步骤或一个澄清问题')
    if len(plan.steps)>limit:
        raise AgentModelResponseError('计划超过剩余工具执行预算')
    ids=[s.id for s in plan.steps]
    if len(ids)!=len(set(ids)):
        raise AgentModelResponseError('计划步骤ID重复')
    writes=[]
    for step in plan.steps:
        if step.tool not in allowed:
            raise AgentModelResponseError('计划工具不属于当前意图的授权目录')
        definition=registry.get(step.tool)
        if not actor.is_active or not has_permission(actor.role,definition.required_permission):
            raise PermissionDeniedError()
        if not definition.read_only:
            if not definition.requires_confirmation:
                raise AgentModelResponseError('副作用工具必须要求人工确认')
            writes.append(step)
        if not set(step.depends_on)<=set(ids) or step.id in step.depends_on:
            raise AgentModelResponseError('计划依赖不存在或自引用')
        references=[*step.bindings.values(),*([step.when.source] if step.when else [])]
        if any(r.step_id not in step.depends_on for r in references):
            raise AgentModelResponseError('结果引用必须声明直接依赖')
        if set(step.arguments)&set(step.bindings):
            raise AgentModelResponseError('参数与绑定不能覆盖同一字段')
        # Validate all static parameters now, then validate bound values again
        # before execution. Unknown/missing static fields are never ignored.
        schema=definition.arguments_schema
        if set(step.bindings)-set(schema.model_fields):
            raise AgentModelResponseError('绑定包含未注册参数')
        partial={**step.arguments}
        if not step.bindings:
            registry.validate_arguments(step.tool,partial)
        elif set(partial)-set(schema.model_fields):
            raise AgentModelResponseError('计划包含未注册参数')
        else:
            required={name for name,field in schema.model_fields.items() if field.is_required()}
            if not required<=set(partial)|set(step.bindings):
                raise AgentModelResponseError('计划遗漏必要输入或结果绑定')
            for name,item in partial.items():
                TypeAdapter(schema.model_fields[name].rebuild_annotation()).validate_python(item)
    visited=set()
    while len(visited)<len(ids):
        ready={s.id for s in plan.steps if s.id not in visited and set(s.depends_on)<=visited}
        if not ready:raise AgentModelResponseError('计划依赖存在循环')
        visited|=ready
    if len(writes)>1:
        raise AgentModelResponseError('每次请求仅允许一个人工审批写操作')
    if writes:
        write=writes[0]
        # A write is a terminal barrier: never pretend later reads observe an
        # operation that has not yet been confirmed/executed.
        if set(write.depends_on)!=set(ids)-{write.id}:
            raise AgentModelResponseError('人工审批必须位于所有只读步骤之后')
    return plan


class ExecutionEvent(Contract):
    node: str
    step_id: str | None = None
    tool: str | None = None
    status: str
    elapsed_ms: float = 0
    error_code: str | None = None
    input_fields: tuple[str,...] = ()
    output_fields: tuple[str,...] = ()
    parallel_group: str | None = None
    result_summary: dict[str,str | int | bool | None] = Field(default_factory=dict)
    attempt: int = 1
    max_attempts: int = 1
    retry_delay_ms: float = 0
    error_category: str | None = None


class ExecutionReport(Contract):
    execution_id: str
    conversation_id: int | None = None
    intent: str
    status: str
    current_node: str
    plan: tuple[dict[str,Any],...] = ()
    events: tuple[ExecutionEvent,...] = ()
    completed_steps: int = 0
    tool_attempts: int = 0
    replans: int = 0
    elapsed_ms: float = 0
    revision: int = 0
    can_resume: bool = False
    recovery_reason: str | None = None
    final_message: str | None = None
    write_outcome: Literal['CANCELLED_BEFORE_COMMIT','COMMITTED','COMPLETION_UNKNOWN'] | None = None
    capabilities: tuple[dict[str,Any],...] = ()
