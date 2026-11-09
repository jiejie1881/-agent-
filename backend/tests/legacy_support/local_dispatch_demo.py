"""Anonymous in-memory scenarios; never load or persist business records."""
import json
from datetime import UTC, date, datetime
from typing import Literal

from app.agent.dispatch_workflow import ShadowDispatchWorkflow
from app.agent.langchain_client import LangChainModelClient
from app.agent.model_types import AgentModelResponse
from app.domain.exceptions import PermissionDeniedError
from app.domain.permissions import Permission, has_permission
from app.schemas.agent_dispatch import ShadowDispatchRequest
from app.schemas.dispatch_candidate import DispatchContext, PlanningModel


class LocalDemoRequest(PlanningModel):
    scene: Literal["normal", "overweight", "terrain"]
    mode: Literal["offline", "real"] = "offline"
    delivery_date: date = date(2026, 11, 10)
    inject_violation: bool = False
    authorize_external: bool = False


def demo_context(scene, day):
    vehicles = [{"id": 1, "code": "DEMO-V1", "plate_number": "匿名车辆1", "vehicle_type_id": 1,
                     "vehicle_type_code": "SMALL_VAN", "vehicle_type_name": "小型面包车",
                     "min_load": 100, "max_load": 500, "is_active": True, "type_active": True,
                     "attendance_exists": True, "available": True, "default_driver_id": 1}]
    if scene == "terrain":
        vehicles.append(dict(vehicles[0], id=2, code="DEMO-V2", plate_number="匿名车辆2",
                             vehicle_type_id=2, vehicle_type_code="BIG_VAN",
                             vehicle_type_name="大型面包车", default_driver_id=2))
    ctx = DispatchContext(
        delivery_date=day, captured_at=datetime.now(UTC), snapshot_version="",
        demands=[{"id": 1, "store_id": 1, "date": day, "period": "MORNING",
                      "quantity": 600 if scene == "overweight" else 200,
                      "priority": "NORMAL", "status": "PENDING", "schedulable": True}],
        stores=[{"id": 1, "code": "DEMO-S1", "name": "匿名演示门店", "route_ids": [1]}],
        routes=[{"id": 1, "code": "DEMO-R1", "name": "匿名线路", "terrain_id": 1, "terrain_name": "普通"}],
        vehicles=vehicles,
        shifts=[{"vehicle_id": v["id"], "period": "MORNING", "driver_id": v["default_driver_id"], "available": True} for v in vehicles],
        terrain_permissions=[(2 if scene == "terrain" else 1, 1)], resource_records={},
    )
    return ctx.model_copy(update={"snapshot_version": ctx.fingerprint()})


class OfflineDemoModel:
    """Scripted candidates, not LLM inference or a replacement dispatch algorithm."""
    async def chat(self, messages, tools):
        payload = json.loads(messages[1].content)
        ctx = payload["context"]
        revision = bool(payload.get("violation_history"))
        scene = self.request.scene
        vehicle = 2 if scene == "terrain" and (revision or not self.request.inject_violation) else 1
        trip = {"vehicle_id": vehicle, "driver_id": vehicle, "period": "MORNING", "trip_no": 1,
                    "route_id": 1, "demand_ids": [1]}
        unassigned = scene == "overweight" and (revision or not self.request.inject_violation)
        return AgentModelResponse(content=json.dumps({
            "candidate_id": "offline-scripted", "delivery_date": ctx["delivery_date"],
            "snapshot_version": ctx["snapshot_version"], "trips": [] if unassigned else [trip],
            "unassigned": [{"demand_id": 1, "explanation": "600kg超过500kg车辆上限，不拆分需求"}] if unassigned else [],
            "planning_explanation": "离线固定候选；修正为预设响应，非实时模型推理",
        }))

    def __init__(self, request):
        self.request = request


def guard(actor, settings):
    if not settings.local_dispatch_demo_enabled or not has_permission(actor.role, Permission.DISPATCH_WRITE):
        raise PermissionDeniedError("本地演示未启用或无调度权限")


async def run_demo(request, actor, settings):
    guard(actor, settings)
    ctx = demo_context(request.scene, request.delivery_date)
    config = settings.model_copy(update={"agent_dispatch_shadow_enabled": True,
                                          "agent_dispatch_shadow_max_revisions": 2})
    if request.mode == "real":
        if not settings.local_dispatch_demo_real_enabled or not request.authorize_external or request.inject_violation:
            raise PermissionDeniedError("真实模型需服务端启用及单独数据/费用确认，禁止真实模式注入")
        if any(x is None for x in (settings.agent_dispatch_shadow_max_cost,
                                  settings.agent_dispatch_shadow_input_price_per_million,
                                  settings.agent_dispatch_shadow_output_price_per_million)):
            raise PermissionDeniedError("真实模式必须配置费用预算及可信费率")
        model = LangChainModelClient(settings=config, max_output_tokens=config.agent_dispatch_shadow_output_tokens)
    else:
        model = OfflineDemoModel(request)
    result = await ShadowDispatchWorkflow(model, lambda day: ctx, config).run(
        ShadowDispatchRequest(delivery_date=request.delivery_date, compare_greedy=True), actor)
    return {"mode": request.mode, "injection": request.inject_violation, "data_source": "ANONYMOUS_IN_MEMORY",
                "context": ctx.model_dump(mode="json"), "result": result.model_dump(mode="json"),
                "persistence": "NO_SAVE_OR_PUBLISH"}
