from datetime import date

import pytest

from app.agent.exceptions import (
    AgentToolArgumentsError,
    AgentToolNotFoundError,
    AgentToolRegistrationError,
)
from app.agent.schemas.tool import (
    GET_VEHICLE_ATTENDANCE_DEFINITION,
    LIST_DELIVERY_DEMANDS_DEFINITION,
    ListDeliveryDemandsArgs,
)
from app.agent.tool_registry import AgentToolRegistry

EXPECTED_TOOL_NAMES = [
    "list_delivery_demands",
    "get_vehicle_attendance",
    "list_dispatch_plans",
    "get_dispatch_plan_detail",
    "get_unassigned_demands",
    "validate_dispatch_plan",
    "search_knowledge_base",
]


def test_registry_contains_all_phase_two_tools_in_stable_order() -> None:
    registry = AgentToolRegistry()

    assert [item.name for item in registry.list_definitions()] == EXPECTED_TOOL_NAMES


def test_get_returns_registered_definition() -> None:
    registry = AgentToolRegistry()

    assert registry.get("get_vehicle_attendance") is GET_VEHICLE_ATTENDANCE_DEFINITION


def test_get_rejects_unknown_tool_with_safe_error() -> None:
    registry = AgentToolRegistry()

    with pytest.raises(AgentToolNotFoundError) as captured:
        registry.get("delete_all_data")

    assert captured.value.code == "AGENT_TOOL_NOT_FOUND"
    assert captured.value.status_code == 400
    assert "delete_all_data" in captured.value.message


def test_validate_arguments_returns_typed_model() -> None:
    registry = AgentToolRegistry()

    arguments = registry.validate_arguments(
        "list_delivery_demands",
        {"date": "2026-09-28", "period": "MORNING"},
    )

    assert isinstance(arguments, ListDeliveryDemandsArgs)
    assert arguments.date == date(2026, 9, 28)
    assert arguments.limit == 20


def test_validate_arguments_converts_invalid_date_to_safe_error() -> None:
    registry = AgentToolRegistry()

    with pytest.raises(AgentToolArgumentsError) as captured:
        registry.validate_arguments(
            "list_delivery_demands",
            {"date": "not-a-date"},
        )

    assert captured.value.code == "AGENT_TOOL_ARGUMENTS_ERROR"
    assert captured.value.status_code == 400
    assert "ValidationError" not in captured.value.message
    assert "pydantic" not in captured.value.message.lower()
    assert "not-a-date" not in captured.value.message


def test_validate_arguments_rejects_extra_fields() -> None:
    registry = AgentToolRegistry()

    with pytest.raises(AgentToolArgumentsError):
        registry.validate_arguments(
            "get_vehicle_attendance",
            {"date": "2026-09-28", "available": True},
        )


@pytest.mark.parametrize("plan_id", [0, -1, "invalid"])
def test_validate_arguments_rejects_invalid_plan_ids(plan_id: object) -> None:
    registry = AgentToolRegistry()

    with pytest.raises(AgentToolArgumentsError):
        registry.validate_arguments(
            "get_dispatch_plan_detail",
            {"plan_id": plan_id},
        )


def test_duplicate_tool_names_are_rejected_immediately() -> None:
    with pytest.raises(AgentToolRegistrationError) as captured:
        AgentToolRegistry(
            [LIST_DELIVERY_DEMANDS_DEFINITION, LIST_DELIVERY_DEMANDS_DEFINITION]
        )

    assert captured.value.code == "AGENT_TOOL_REGISTRATION_ERROR"
    assert captured.value.status_code == 500


def test_openai_tools_preserve_registry_order_and_schema() -> None:
    registry = AgentToolRegistry()

    tools = registry.to_openai_tools()

    assert len(tools) == 7
    assert [tool["function"]["name"] for tool in tools] == EXPECTED_TOOL_NAMES
    assert all(tool["type"] == "function" for tool in tools)
    assert all(tool["function"]["parameters"]["type"] == "object" for tool in tools)
    assert tools[0]["function"]["parameters"]["required"] == ["date"]


def test_list_definitions_is_immutable_snapshot() -> None:
    definitions = AgentToolRegistry().list_definitions()

    assert isinstance(definitions, tuple)
    with pytest.raises(TypeError):
        definitions[0] = GET_VEHICLE_ATTENDANCE_DEFINITION


def test_registry_has_no_execution_api() -> None:
    registry = AgentToolRegistry()

    assert not hasattr(registry, "execute")
