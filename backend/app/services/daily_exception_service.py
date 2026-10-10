"""Factual daily exception snapshot; no dispatch or execution mutations."""

from datetime import date

from sqlalchemy.orm import Session

from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryStopStatus,
    DispatchPlanStatus,
)
from app.domain.exceptions import ConflictError, NotFoundError
from app.repositories.daily_exception_repository import DailyExceptionRepository
from app.repositories.dispatch_plan_repository import DispatchPlanRepository


class DailyExceptionService:
    def __init__(self, session: Session) -> None:
        self.repository = DailyExceptionRepository(session)
        self.plans = DispatchPlanRepository(session)

    def report(
        self, delivery_date: date, plan_id: int | None = None, example_limit: int = 10
    ) -> dict:
        if plan_id is None:
            plan_id = self.repository.reference_plan_id(delivery_date)
            selection = "AUTO_PUBLISHED_OR_LATEST_DRAFT" if plan_id else "NO_PLAN"
        else:
            selection = "EXPLICIT_PLAN"
        plan = self.plans.get(plan_id) if plan_id is not None else None
        if plan_id is not None and plan is None:
            raise NotFoundError("派车方案不存在")
        if plan is not None and plan.delivery_date != delivery_date:
            raise ConflictError("方案配送日期与查询日期不一致")

        represented_ids = set()
        represented_assigned_ids: set[int] = set()
        if plan is not None:
            represented_assigned_ids = {
                detail.delivery_demand_id
                for order in plan.orders
                for detail in order.details
            }
            represented_ids = represented_assigned_ids | {
                item.delivery_demand_id for item in plan.unassigned_demands
            }
        pending_outside = [
            demand
            for demand in self.repository.planning_demands(delivery_date)
            if demand.id not in represented_ids
        ]

        unavailable = []
        failed_stops = []
        unassigned = []
        if plan is not None:
            attendance = self.repository.attendance_by_vehicle(
                delivery_date, {order.vehicle_id for order in plan.orders}
            )
            for order in sorted(plan.orders, key=lambda item: item.id):
                record = attendance.get(order.vehicle_id)
                issues = []
                if record is None:
                    issues.append("ATTENDANCE_MISSING")
                elif not record.available:
                    issues.append("ATTENDANCE_UNAVAILABLE")
                if not order.vehicle.is_active:
                    issues.append("VEHICLE_INACTIVE")
                if not order.vehicle.vehicle_type.is_active:
                    issues.append("VEHICLE_TYPE_INACTIVE")
                if issues:
                    unavailable.append(
                        {
                            "order_id": order.id,
                            "vehicle_id": order.vehicle_id,
                            "vehicle_plate": order.vehicle.plate_number,
                            "period": order.period.value,
                            "trip_no": order.trip_no,
                            "attendance": (
                                "MISSING" if record is None
                                else "AVAILABLE" if record.available
                                else "UNAVAILABLE"
                            ),
                            "issues": issues,
                        }
                    )
                if plan.status == DispatchPlanStatus.PUBLISHED:
                    for detail in sorted(order.details, key=lambda item: item.id):
                        if detail.delivery_status == DeliveryStopStatus.FAILED:
                            failed_stops.append(
                                {
                                    "stop_id": detail.id,
                                    "order_id": order.id,
                                    "demand_id": detail.delivery_demand_id,
                                    "store_name": detail.delivery_demand.store.name,
                                    "vehicle_plate": order.vehicle.plate_number,
                                    "vehicle_code": order.vehicle.code,
                                    "actual_driver_id": order.actual_driver_id,
                                    "actual_driver_name": order.driver_name_snapshot,
                                    "current_driver_username": (
                                        order.vehicle.driver.username
                                        if order.vehicle.driver else None
                                    ),
                                    "arrived_at": detail.arrived_at,
                                    "failure_reason": (
                                        detail.failure_reason.value
                                        if detail.failure_reason else None
                                    ),
                                }
                            )
            unassigned = [
                {
                    "demand_id": item.delivery_demand_id,
                    "store_name": item.delivery_demand.store.name,
                    "priority": item.delivery_demand.priority.value,
                    "reasons": list(item.reasons),
                }
                for item in sorted(plan.unassigned_demands, key=lambda item: item.id)
                if item.delivery_demand_id not in represented_assigned_ids
                and item.delivery_demand.date == delivery_date
                and item.delivery_demand.status in {
                    DeliveryDemandStatus.PENDING,
                    DeliveryDemandStatus.PLANNED,
                }
            ]

        pending_items = [
            {
                "demand_id": item.id,
                "store_name": item.store.name,
                "priority": item.priority.value,
                "period": item.period.value,
            }
            for item in pending_outside
        ]
        notices = []
        if plan is None:
            notices.append("该日期没有已发布或草稿方案；仅展示当前可计划的需求。")
        elif plan.status == DispatchPlanStatus.DRAFT:
            notices.append("参考方案仍为DRAFT，仅供规划复核，不代表正在执行。")
        elif plan.status == DispatchPlanStatus.CANCELLED:
            notices.append("显式选择的方案已取消，仅供历史查询，不代表当前执行方案。")

        def section(items: list[dict]) -> dict:
            return {
                "count": len(items),
                "examples": items[:example_limit],
                "truncated": len(items) > example_limit,
            }

        return {
            "delivery_date": delivery_date,
            "reference_plan": (
                {
                    "id": plan.id,
                    "version": plan.version,
                    "status": plan.status.value,
                    "selection": selection,
                }
                if plan else None
            ),
            "plan_unassigned": section(unassigned),
            "pending_outside_reference_plan": section(pending_items),
            "plan_vehicle_unavailable": section(unavailable),
            "failed_stops": section(failed_stops),
            "notices": notices,
            "note": (
                "只读查询时刻快照。未分配记录属于所选方案；方案外只列PENDING及由有效草稿占用的PLANNED需求。"
                "实际执行司机取任务归属快照，缺失时不推断；兼容字段current_driver_username仍为当前绑定账号。到店时间不是失败发生时间。"
                "不依据本报告推断配送延误，也不修改派车或配送状态。"
            ),
        }
