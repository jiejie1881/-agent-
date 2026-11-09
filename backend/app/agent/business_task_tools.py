"""Business projections and non-persistent dispatch preview; no new algorithms."""
from collections import Counter
from dataclasses import replace
from datetime import date
from uuid import uuid4
from typing import Literal

from pydantic import Field

from app.agent.schemas.tool import AgentToolDefinition, PaginatedToolArgs, StrictToolArgs
from app.agent.tool_execution import AgentToolExecutor
from app.domain.enums import DeliveryPeriod
from app.domain.permissions import Permission
from app.domain.exceptions import BusinessError


class DayArgs(StrictToolArgs):
    date: date


class VehicleQuery(PaginatedToolArgs):
    pass


class ExceptionQuery(DayArgs):
    plan_id: int | None = Field(default=None,gt=0)


class ExceptionCasesQuery(PaginatedToolArgs):
    status: Literal['OPEN','IN_PROGRESS','RESOLVED'] | None = None


EXTRA_DEFINITIONS = tuple(AgentToolDefinition(name=name,description=description,arguments_schema=schema)
    for name,description,schema in [
        ('list_vehicles','分页查询车辆及车型、额定载重和运营状态；不修改车辆。',VehicleQuery),
        ('list_drivers','查询指定日期司机状态、出勤及排班摘要，不包含电话或凭据。',DayArgs),
        ('list_transport_tasks','查询指定日期各版本方案中的运输任务，返回方案状态，不将草稿当成正式任务。',DayArgs),
        ('get_daily_exceptions','查询指定日期异常工作台及关联需求/运输任务ID，不修改或结案工单。',ExceptionQuery),
        ('analyze_capacity','根据当天真实业务快照分析分时段可用运力和需求；估计运力不保证可行调度。',DayArgs),
        ('preview_dispatch_candidate','复用现有调度引擎生成内存候选并执行确定性校验，不创建草稿、不发布、不修改任何业务状态。',DayArgs),
    ]) + (AgentToolDefinition(name='list_exception_cases',
        description='只读查询真实异常工单及来源需求、运输任务、方案ID，权限与异常工作台一致；不结案、不修改状态。',
        arguments_schema=ExceptionCasesQuery,required_permission=Permission.OPERATIONS_WRITE),)


class BusinessProjectionTool(AgentToolExecutor):
    def __init__(self,session,definition):
        self.session=session
        self.name,self.arguments_type=definition.name,definition.arguments_schema

    def _execute(self,arguments,context):
        from app.services.dispatch_plan_service import DispatchPlanService
        from app.services.driver_scheduling_service import DriverSchedulingService
        if self.name=='list_vehicles':
            from app.services.vehicle_service import VehicleService
            rows=VehicleService(self.session).list(arguments.offset,arguments.limit)
            return dict(items=[dict(id=v.id,code=v.code,vehicle_type=v.vehicle_type.name,
                rated_load=v.rated_load,is_active=v.is_active,operating_status=v.operating_status,
                driver_id=v.driver_user_id) for v in rows],returned_count=len(rows),
                offset=arguments.offset,limit=arguments.limit,truncated=len(rows)==arguments.limit)
        if self.name=='list_drivers':
            rows=DriverSchedulingService(self.session).list_drivers(arguments.date)
            return dict(date=arguments.date,items=[{k:r[k] for k in ('id','display_name','is_active',
                'default_vehicle_id','attendance','schedules','today_task_count')} for r in rows[:100]],
                returned_count=min(100,len(rows)),truncated=len(rows)>100)
        if self.name=='list_transport_tasks':
            plans=DispatchPlanService(self.session).list(arguments.date,0,20)
            items=[]
            for plan in plans:
                for order in DispatchPlanService(self.session).get(plan.id).orders:
                    items.append(dict(order_id=order.id,plan_id=plan.id,plan_status=plan.status.value,
                        version=plan.version,vehicle_id=order.vehicle.id,period=order.period.value,
                        trip_no=order.trip_no,total_load=order.total_load,
                        demand_ids=[d.delivery_demand_id for d in order.details]))
            return dict(items=items[:100],returned_count=min(100,len(items)),
                        truncated=len(items)>100 or len(plans)==20)
        if self.name=='get_daily_exceptions':
            from app.services.daily_exception_service import DailyExceptionService
            return DailyExceptionService(self.session).report(arguments.date,arguments.plan_id)
        if self.name=='list_exception_cases':
            from app.services.exception_case_service import ExceptionCaseService
            from app.models.delivery_demand import DeliveryDemand
            from app.models.dispatch_plan import DispatchOrder, DispatchOrderDetail, DeliveryProof
            rows=ExceptionCaseService(self.session).list(context.current_user,arguments.status,arguments.offset,arguments.limit)
            items=[]
            for case in rows:
                item=dict(id=case.id,category=case.category,status=case.status,reason=case.reason,revision=case.revision)
                object_id=int(case.source_key.rsplit(':',1)[1])
                if case.category=='UNASSIGNED_DEMAND':
                    demand=self.session.get(DeliveryDemand,object_id)
                    if demand:item.update(demand_id=demand.id,store_id=demand.store_id,date=demand.date)
                else:
                    detail=None;order=None
                    if case.category in {'FAILED_STOP','MISSING_PROOF','STATE_CONFLICT'}:
                        detail=self.session.get(DispatchOrderDetail,object_id)
                    elif case.category=='REJECTED_PROOF':
                        proof=self.session.get(DeliveryProof,object_id)
                        detail=self.session.get(DispatchOrderDetail,proof.dispatch_order_detail_id) if proof else None
                    elif case.category=='VEHICLE_UNAVAILABLE':order=self.session.get(DispatchOrder,object_id)
                    if detail:
                        item.update(demand_id=detail.delivery_demand_id,detail_id=detail.id)
                        order=detail.dispatch_order
                    if order:item.update(order_id=order.id,plan_id=order.plan_id,date=order.plan.delivery_date)
                items.append(item)
            return dict(items=items,returned_count=len(items),offset=arguments.offset,limit=arguments.limit,
                        truncated=len(items)==arguments.limit)
        from app.services.dispatch_context_service import DispatchContextService
        snapshot=DispatchContextService(self.session).load(arguments.date)
        if len(snapshot.demands)>1000 or len(snapshot.vehicles)>200:
            raise BusinessError('数据量超过交互式Agent预览上限，请使用调度工作台',422,'AGENT_PREVIEW_LIMIT')
        if self.name=='analyze_capacity':
            values=[]
            for period in DeliveryPeriod:
                active={s.vehicle_id for s in snapshot.shifts if s.period==period and s.available}
                demands=[d for d in snapshot.demands if d.period==period and d.schedulable]
                vehicles=[v for v in snapshot.vehicles if v.id in active and v.available and v.is_active and v.type_active]
                values.append(dict(period=period.value,demand_count=len(demands),
                    demand_kg=sum(d.quantity for d in demands),vehicles=len(vehicles),
                    single_trip_upper_kg=sum(v.max_load for v in vehicles)))
            return dict(snapshot_version=snapshot.snapshot_version,periods=values,
                        warning='仅为单趟容量上界；线路、地形、最低载重和趟次约束需候选校验，不保证可行')
        return self._candidate(arguments.date,snapshot)

    def _candidate(self,day,snapshot):
        from app.dispatch_engine.dispatch_engine import DispatchEngine
        from app.repositories.dispatch_engine_repository import DispatchEngineRepository
        from app.schemas.dispatch_candidate import CandidateTrip, CandidateUnassigned, DispatchCandidate
        from app.services.dispatch_context_service import DispatchContextService
        from app.services.dispatch_candidate_validation_service import DispatchCandidateValidator
        data=DispatchEngineRepository(self.session).load(day)
        shifts={(s.vehicle_id,s.period):s for s in snapshot.shifts if s.available}
        counts=Counter();trips=[];unassigned_reasons={}
        for period in DeliveryPeriod:
            eligible=[replace(v,daily_trip_limit=v.daily_trip_limit-counts[v.id] if v.daily_trip_limit else None)
                for v in data.vehicles if (v.id,period) in shifts and
                (v.daily_trip_limit is None or counts[v.id]<v.daily_trip_limit)]
            result=DispatchEngine().dispatch(replace(data,vehicles=tuple(eligible),
                demands=tuple(d for d in data.demands if d.period==period)))
            for item in result.unassigned_demands:
                unassigned_reasons[item.demand.id]='；'.join(item.reasons)
            if not eligible:
                codes=sorted({s.violation_code for s in snapshot.shifts if s.period==period and not s.available and s.violation_code})
                for d in data.demands:
                    if d.period==period:unassigned_reasons[d.id]='无通过司机/车辆可用性校验的车辆；'+','.join(codes)
            for t in result.trips:
                counts[t.vehicle.id]+=1
                trips.append(CandidateTrip(vehicle_id=t.vehicle.id,driver_id=shifts[t.vehicle.id,period].driver_id,
                    period=period,trip_no=t.trip_no,route_id=t.route.id,demand_ids=tuple(d.demand.id for d in t.demands)))
        assigned={i for t in trips for i in t.demand_ids}
        candidate=DispatchCandidate(candidate_id=uuid4().hex,delivery_date=day,snapshot_version=snapshot.snapshot_version,
            trips=tuple(trips),unassigned=tuple(CandidateUnassigned(demand_id=d.id,
                explanation=(unassigned_reasons.get(d.id) or '未满足现有调度约束，请检查运力与业务配置')[:1000])
                for d in snapshot.demands if d.schedulable and d.id not in assigned),
            planning_explanation='复用现有DispatchEngine，并以DispatchCandidateValidator校验载重、线路、地形、时段、司机、车辆出勤及日趟次约束。')
        validation=DispatchCandidateValidator().validate(candidate,snapshot,
            current_context=DispatchContextService(self.session).load(day))
        return dict(candidate=candidate.model_dump(mode='json'),validation=validation.model_dump(mode='json'),
                    persisted=False,published=False,requires_manual_adoption=True,
                    constraint_authority='DispatchEngine + DispatchCandidateValidator',policy_version=snapshot.policy_version)


def build_business_task_executors(session):
    return [BusinessProjectionTool(session,d) for d in EXTRA_DEFINITIONS]
