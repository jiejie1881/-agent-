from __future__ import annotations

from enum import Enum
from typing import Any

from app.agent.schemas.tool import (
    GetDispatchPlanDetailArgs,
    GetUnassignedDemandsArgs,
    GetVehicleAttendanceArgs,
    ListDeliveryDemandsArgs,
    ListDispatchPlansArgs,
    ValidateDispatchPlanArgs,
)
from app.agent.tool_execution import (
    AgentToolContext,
    AgentToolExecutor,
    AgentToolExecutorRegistry,
)
from app.agent.tool_registry import AgentToolRegistry
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.vehicle_attendance_service import VehicleAttendanceService


def _enum_value(value: object) -> object:
    return value.value if isinstance(value, Enum) else value


def _store_data(store: object) -> dict[str, Any]:
    return {
        "id": store.id,
        "code": store.code,
        "name": store.name,
    }


def _unassigned_item_data(item: object) -> dict[str, Any]:
    return {
        "demand_id": item.delivery_demand_id,
        "store": {
            "id": item.store_id,
            "code": item.store_code,
            "name": item.store_name,
        },
        "period": _enum_value(item.period),
        "quantity": item.quantity,
        "reasons": list(item.reasons),
    }


class ListDeliveryDemandsTool(AgentToolExecutor[ListDeliveryDemandsArgs]):
    name = "list_delivery_demands"
    arguments_type = ListDeliveryDemandsArgs

    def __init__(self, service: DeliveryDemandService) -> None:
        self.service = service

    def _execute(
        self,
        arguments: ListDeliveryDemandsArgs,
        context: AgentToolContext,
    ) -> dict[str, Any]:
        items = self.service.list(
            arguments.date,
            arguments.store_id,
            arguments.period,
            arguments.offset,
            arguments.limit,
        )
        return {
            "offset": arguments.offset,
            "limit": arguments.limit,
            "returned_count": len(items),
            "items": [
                {
                    "id": item.id,
                    "delivery_date": item.date,
                    "period": _enum_value(item.period),
                    "store": _store_data(item.store),
                    "quantity": item.quantity,
                    "status": _enum_value(item.status),
                }
                for item in items
            ],
        }


class GetVehicleAttendanceTool(AgentToolExecutor[GetVehicleAttendanceArgs]):
    name = "get_vehicle_attendance"
    arguments_type = GetVehicleAttendanceArgs
    QUERY_LIMIT = 100

    def __init__(self, service: VehicleAttendanceService) -> None:
        self.service = service

    def _execute(
        self,
        arguments: GetVehicleAttendanceArgs,
        context: AgentToolContext,
    ) -> dict[str, Any]:
        records = self.service.list(
            arguments.date,
            arguments.vehicle_id,
            0,
            self.QUERY_LIMIT,
        )
        return {
            "date": arguments.date,
            "vehicle_id_filter": arguments.vehicle_id,
            "returned_count": len(records),
            "truncated": len(records) == self.QUERY_LIMIT,
            "vehicles": [
                {
                    "vehicle_id": record.vehicle_id,
                    "plate_number": record.vehicle.plate_number,
                    "vehicle_type": {
                        "code": _enum_value(record.vehicle.vehicle_type.code),
                        "name": record.vehicle.vehicle_type.name,
                    },
                    "available": record.available,
                }
                for record in records
            ],
        }


class ListDispatchPlansTool(AgentToolExecutor[ListDispatchPlansArgs]):
    name = "list_dispatch_plans"
    arguments_type = ListDispatchPlansArgs

    def __init__(self, service: DispatchPlanService) -> None:
        self.service = service

    def _execute(
        self,
        arguments: ListDispatchPlansArgs,
        context: AgentToolContext,
    ) -> dict[str, Any]:
        plans = self.service.list(
            arguments.delivery_date,
            arguments.offset,
            arguments.limit,
        )
        return {
            "offset": arguments.offset,
            "limit": arguments.limit,
            "returned_count": len(plans),
            "items": [
                {
                    "id": plan.id,
                    "delivery_date": plan.delivery_date,
                    "version": plan.version,
                    "status": _enum_value(plan.status),
                    "created_at": plan.created_at,
                }
                for plan in plans
            ],
        }


class GetDispatchPlanDetailTool(
    AgentToolExecutor[GetDispatchPlanDetailArgs]
):
    name = "get_dispatch_plan_detail"
    arguments_type = GetDispatchPlanDetailArgs

    def __init__(self, service: DispatchPlanService) -> None:
        self.service = service

    def _execute(
        self,
        arguments: GetDispatchPlanDetailArgs,
        context: AgentToolContext,
    ) -> dict[str, Any]:
        plan = self.service.get(arguments.plan_id)
        return {
            "plan_id": plan.id,
            "delivery_date": plan.delivery_date,
            "version": plan.version,
            "status": _enum_value(plan.status),
            "created_at": plan.created_at,
            "orders": [
                {
                    "order_id": order.id,
                    "vehicle": {
                        "id": order.vehicle.id,
                        "plate_number": order.vehicle.plate_number,
                        "vehicle_type": {
                            "code": _enum_value(order.vehicle.vehicle_type_code),
                            "name": order.vehicle.vehicle_type_name,
                        },
                    },
                    "period": _enum_value(order.period),
                    "trip_no": order.trip_no,
                    "route": {
                        "id": order.route.id,
                        "code": order.route.code,
                        "name": order.route.name,
                    },
                    "total_load": order.total_load,
                    "demands": [
                        {
                            "demand_id": detail.delivery_demand_id,
                            "store": {
                                "id": detail.store_id,
                                "code": detail.store_code,
                                "name": detail.store_name,
                            },
                            "quantity": detail.quantity,
                            "status": _enum_value(detail.status),
                        }
                        for detail in order.details
                    ],
                }
                for order in plan.orders
            ],
            "unassigned_demands": [
                _unassigned_item_data(item) for item in plan.unassigned_demands
            ],
        }


class GetUnassignedDemandsTool(
    AgentToolExecutor[GetUnassignedDemandsArgs]
):
    name = "get_unassigned_demands"
    arguments_type = GetUnassignedDemandsArgs

    def __init__(self, service: DispatchPlanService) -> None:
        self.service = service

    def _execute(
        self,
        arguments: GetUnassignedDemandsArgs,
        context: AgentToolContext,
    ) -> dict[str, Any]:
        plan = self.service.get(arguments.plan_id)
        items = [
            _unassigned_item_data(item) for item in plan.unassigned_demands
        ]
        return {
            "plan_id": plan.id,
            "count": len(items),
            "items": items,
        }


class ValidateDispatchPlanTool(AgentToolExecutor[ValidateDispatchPlanArgs]):
    name = "validate_dispatch_plan"
    arguments_type = ValidateDispatchPlanArgs

    def __init__(self, service: DispatchPlanService) -> None:
        self.service = service

    def _execute(
        self,
        arguments: ValidateDispatchPlanArgs,
        context: AgentToolContext,
    ) -> dict[str, Any]:
        result = self.service.validate_plan(arguments.plan_id)
        return {
            "plan_id": result.plan_id,
            "valid": result.valid,
            "issues": list(result.issues),
        }


def build_read_only_tool_executors(
    *,
    delivery_demand_service: DeliveryDemandService,
    vehicle_attendance_service: VehicleAttendanceService,
    dispatch_plan_service: DispatchPlanService,
)-> list[AgentToolExecutor[Any]]:
    return [
            ListDeliveryDemandsTool(delivery_demand_service),
            GetVehicleAttendanceTool(vehicle_attendance_service),
            ListDispatchPlansTool(dispatch_plan_service),
            GetDispatchPlanDetailTool(dispatch_plan_service),
            GetUnassignedDemandsTool(dispatch_plan_service),
            ValidateDispatchPlanTool(dispatch_plan_service),
        ]


def build_read_only_tool_executor_registry(
    *,
    delivery_demand_service: DeliveryDemandService,
    vehicle_attendance_service: VehicleAttendanceService,
    dispatch_plan_service: DispatchPlanService,
    definition_registry: AgentToolRegistry | None = None,
) -> AgentToolExecutorRegistry:
    return AgentToolExecutorRegistry(
        build_read_only_tool_executors(
            delivery_demand_service=delivery_demand_service,
            vehicle_attendance_service=vehicle_attendance_service,
            dispatch_plan_service=dispatch_plan_service,
        ),
        definition_registry=definition_registry,
    )
