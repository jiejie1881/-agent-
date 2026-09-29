import asyncio
import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from app.agent.exceptions import AgentToolExecutionError
from app.agent.read_only_tools import build_read_only_tool_executor_registry
from app.agent.tool_execution import AgentToolContext
from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryPeriod,
    DispatchPlanStatus,
    UserRole,
    VehicleTypeCode,
)
from app.domain.exceptions import ConflictError, NotFoundError
from app.models.audit_log import AuditLog
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchPlan
from app.models.user import User
from app.schemas.dispatch_plan import DispatchPlanValidationResponse
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.vehicle_attendance_service import VehicleAttendanceService
from tests.test_dispatch_plan_publish_validation import setup_draft_plan


def run_tool(registry, name: str, arguments: dict, context: AgentToolContext):
    return asyncio.run(registry.execute(name, arguments, context))


@pytest.fixture
def tool_context() -> AgentToolContext:
    return AgentToolContext(
        current_user=User(
            id=99,
            username="agent-viewer",
            password_hash="must-never-be-serialized",
            role=UserRole.VIEWER,
            is_active=True,
        ),
        request_id="request-001",
    )


@pytest.fixture
def fake_services():
    delivery_demand_service = Mock(spec=DeliveryDemandService)
    vehicle_attendance_service = Mock(spec=VehicleAttendanceService)
    dispatch_plan_service = Mock(spec=DispatchPlanService)
    registry = build_read_only_tool_executor_registry(
        delivery_demand_service=delivery_demand_service,
        vehicle_attendance_service=vehicle_attendance_service,
        dispatch_plan_service=dispatch_plan_service,
    )
    return (
        registry,
        delivery_demand_service,
        vehicle_attendance_service,
        dispatch_plan_service,
    )


def fake_unassigned(reason: str = "没有满足条件的可用车辆"):
    return SimpleNamespace(
        delivery_demand_id=20,
        store_id=3,
        store_code="S003",
        store_name="门店三",
        period=DeliveryPeriod.AFTERNOON,
        quantity=Decimal("900.00"),
        reasons=[reason],
    )


def fake_plan(*, unassigned=None):
    detail = SimpleNamespace(
        delivery_demand_id=10,
        store_id=1,
        store_code="S001",
        store_name="门店一",
        quantity=Decimal("350.00"),
        status=DeliveryDemandStatus.PLANNED,
    )
    order = SimpleNamespace(
        id=5,
        vehicle=SimpleNamespace(
            id=7,
            plate_number="湘A001",
            vehicle_type_code=VehicleTypeCode.BIG_VAN,
            vehicle_type_name="大包",
        ),
        period=DeliveryPeriod.MORNING,
        trip_no=1,
        route=SimpleNamespace(id=2, code="R002", name="二号线路"),
        total_load=Decimal("350.00"),
        details=[detail],
    )
    return SimpleNamespace(
        id=12,
        delivery_date=date(2026, 9, 28),
        version=2,
        status=DispatchPlanStatus.DRAFT,
        created_at=datetime(2026, 9, 28, 8, 30),
        orders=[order],
        unassigned_demands=list(unassigned or []),
    )


def test_list_delivery_demands_calls_service_and_normalizes_result(
    fake_services, tool_context
) -> None:
    registry, service, _, _ = fake_services
    service.list.return_value = [
        SimpleNamespace(
            id=10,
            date=date(2026, 9, 28),
            period=DeliveryPeriod.MORNING,
            store=SimpleNamespace(id=1, code="S001", name="门店一"),
            quantity=Decimal("125.50"),
            status=DeliveryDemandStatus.PENDING,
        )
    ]

    result = run_tool(
        registry,
        "list_delivery_demands",
        {
            "date": "2026-09-28",
            "period": "MORNING",
            "offset": 5,
            "limit": 10,
        },
        tool_context,
    )

    service.list.assert_called_once_with(
        date(2026, 9, 28), None, DeliveryPeriod.MORNING, 5, 10
    )
    assert result.tool_name == "list_delivery_demands"
    assert result.data["returned_count"] == 1
    assert result.data["items"][0] == {
        "id": 10,
        "delivery_date": "2026-09-28",
        "period": "MORNING",
        "store": {"id": 1, "code": "S001", "name": "门店一"},
        "quantity": "125.50",
        "status": "PENDING",
    }
    serialized = json.loads(result.to_json())
    assert serialized == result.model_dump()
    assert "must-never-be-serialized" not in result.to_json()


@pytest.mark.parametrize("vehicle_id", [None, 7])
def test_get_vehicle_attendance_passes_optional_vehicle_filter(
    fake_services, tool_context, vehicle_id
) -> None:
    registry, _, service, _ = fake_services
    service.list.return_value = [
        SimpleNamespace(
            vehicle_id=7,
            available=True,
            vehicle=SimpleNamespace(
                plate_number="湘A001",
                vehicle_type=SimpleNamespace(
                    code=VehicleTypeCode.SMALL_VAN,
                    name="小包",
                ),
            ),
        )
    ]
    payload = {"date": "2026-09-28"}
    if vehicle_id is not None:
        payload["vehicle_id"] = vehicle_id

    result = run_tool(
        registry, "get_vehicle_attendance", payload, tool_context
    )

    service.list.assert_called_once_with(date(2026, 9, 28), vehicle_id, 0, 100)
    assert result.data["date"] == "2026-09-28"
    assert result.data["vehicles"] == [
        {
            "vehicle_id": 7,
            "plate_number": "湘A001",
            "vehicle_type": {"code": "SMALL_VAN", "name": "小包"},
            "available": True,
        }
    ]


def test_list_dispatch_plans_passes_pagination_and_returns_summary(
    fake_services, tool_context
) -> None:
    registry, _, _, service = fake_services
    service.list.return_value = [fake_plan()]

    result = run_tool(
        registry,
        "list_dispatch_plans",
        {"delivery_date": "2026-09-28", "offset": 2, "limit": 5},
        tool_context,
    )

    service.list.assert_called_once_with(date(2026, 9, 28), 2, 5)
    assert result.data["items"] == [
        {
            "id": 12,
            "delivery_date": "2026-09-28",
            "version": 2,
            "status": "DRAFT",
            "created_at": "2026-09-28T08:30:00",
        }
    ]


def test_get_dispatch_plan_detail_returns_trips_and_unassigned_demands(
    fake_services, tool_context
) -> None:
    registry, _, _, service = fake_services
    service.get.return_value = fake_plan(unassigned=[fake_unassigned()])

    result = run_tool(
        registry,
        "get_dispatch_plan_detail",
        {"plan_id": 12},
        tool_context,
    )

    service.get.assert_called_once_with(12)
    assert result.data["version"] == 2
    assert result.data["orders"][0]["trip_no"] == 1
    assert result.data["orders"][0]["vehicle"]["plate_number"] == "湘A001"
    assert result.data["orders"][0]["demands"][0]["demand_id"] == 10
    assert result.data["unassigned_demands"][0]["demand_id"] == 20


def test_get_unassigned_demands_uses_reasons_returned_by_service(
    fake_services, tool_context
) -> None:
    registry, _, _, service = fake_services
    reason = "车辆最大载重不足"
    service.get.return_value = fake_plan(unassigned=[fake_unassigned(reason)])

    result = run_tool(
        registry,
        "get_unassigned_demands",
        {"plan_id": 12},
        tool_context,
    )

    service.get.assert_called_once_with(12)
    assert result.data["count"] == 1
    assert result.data["items"][0]["reasons"] == [reason]


@pytest.mark.parametrize(
    ("issues", "expected_valid"),
    [
        ([], True),
        (
            [
                {
                    "code": "MIN_LOAD_NOT_MET",
                    "message": "低于最低载重",
                    "order_id": 5,
                }
            ],
            False,
        ),
    ],
)
def test_validate_dispatch_plan_returns_service_validation_result(
    fake_services, tool_context, issues, expected_valid
) -> None:
    registry, _, _, service = fake_services
    service.validate_plan.return_value = DispatchPlanValidationResponse(
        plan_id=12,
        valid=expected_valid,
        issues=issues,
    )

    result = run_tool(
        registry,
        "validate_dispatch_plan",
        {"plan_id": 12},
        tool_context,
    )

    service.validate_plan.assert_called_once_with(12)
    assert result.data == {
        "plan_id": 12,
        "valid": expected_valid,
        "issues": issues,
    }
    assert not hasattr(service, "publish") or not service.publish.called


@pytest.mark.parametrize(
    "service_error",
    [NotFoundError("派车方案不存在"), ConflictError("方案状态冲突")],
)
def test_service_business_errors_become_safe_tool_execution_errors(
    fake_services, tool_context, service_error
) -> None:
    registry, _, _, service = fake_services
    service.get.side_effect = service_error

    with pytest.raises(AgentToolExecutionError) as captured:
        run_tool(
            registry,
            "get_dispatch_plan_detail",
            {"plan_id": 404},
            tool_context,
        )

    assert captured.value.code == "AGENT_TOOL_EXECUTION_ERROR"
    assert service_error.message in captured.value.message
    assert "Traceback" not in captured.value.message


def test_unexpected_executor_error_does_not_leak_internal_details(
    fake_services, tool_context
) -> None:
    registry, service, _, _ = fake_services
    service.list.side_effect = RuntimeError(
        "mysql://root:secret@db/private SQL SELECT password_hash"
    )

    with pytest.raises(AgentToolExecutionError) as captured:
        run_tool(
            registry,
            "list_delivery_demands",
            {"date": "2026-09-28"},
            tool_context,
        )

    assert captured.value.status_code == 500
    assert "secret" not in captured.value.message
    assert "SELECT" not in captured.value.message
    assert "password_hash" not in captured.value.message


def test_read_only_tools_integrate_with_services_without_mutating_plan(
    client, session
) -> None:
    data = setup_draft_plan(client)
    plan_id = data["generated"]["plan_id"]
    demand_id = data["demand"]["id"]
    current_user = session.scalar(select(User).where(User.username == "test-admin"))
    context = AgentToolContext(current_user=current_user)
    registry = build_read_only_tool_executor_registry(
        delivery_demand_service=DeliveryDemandService(session),
        vehicle_attendance_service=VehicleAttendanceService(session),
        dispatch_plan_service=DispatchPlanService(session),
    )
    before_plan = session.get(DispatchPlan, plan_id)
    before_demand = session.get(DeliveryDemand, demand_id)
    before_snapshot = (
        before_plan.status,
        before_demand.status,
        session.scalar(select(func.count()).select_from(DispatchPlan)),
        session.scalar(select(func.count()).select_from(AuditLog)),
    )

    demands = run_tool(
        registry,
        "list_delivery_demands",
        {"date": "2026-09-24"},
        context,
    )
    detail = run_tool(
        registry,
        "get_dispatch_plan_detail",
        {"plan_id": plan_id},
        context,
    )
    validation = run_tool(
        registry,
        "validate_dispatch_plan",
        {"plan_id": plan_id},
        context,
    )

    session.expire_all()
    after_plan = session.get(DispatchPlan, plan_id)
    after_demand = session.get(DeliveryDemand, demand_id)
    after_snapshot = (
        after_plan.status,
        after_demand.status,
        session.scalar(select(func.count()).select_from(DispatchPlan)),
        session.scalar(select(func.count()).select_from(AuditLog)),
    )
    assert demands.data["items"][0]["id"] == demand_id
    assert detail.data["plan_id"] == plan_id
    assert validation.data == {"plan_id": plan_id, "valid": True, "issues": []}
    assert before_snapshot == after_snapshot
    assert after_plan.status == DispatchPlanStatus.DRAFT
    assert after_demand.status == DeliveryDemandStatus.PLANNED
