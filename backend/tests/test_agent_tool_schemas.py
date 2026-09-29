from datetime import date
import json

import pytest
from pydantic import ValidationError

from app.agent.schemas.tool import (
    GET_DISPATCH_PLAN_DETAIL_DEFINITION,
    GET_UNASSIGNED_DEMANDS_DEFINITION,
    GET_VEHICLE_ATTENDANCE_DEFINITION,
    LIST_DELIVERY_DEMANDS_DEFINITION,
    LIST_DISPATCH_PLANS_DEFINITION,
    VALIDATE_DISPATCH_PLAN_DEFINITION,
    GetDispatchPlanDetailArgs,
    GetUnassignedDemandsArgs,
    GetVehicleAttendanceArgs,
    ListDeliveryDemandsArgs,
    ListDispatchPlansArgs,
    ValidateDispatchPlanArgs,
)
from app.domain.enums import DeliveryPeriod


def test_list_delivery_demands_accepts_supported_filters() -> None:
    arguments = ListDeliveryDemandsArgs.model_validate(
        {
            "date": "2026-09-28",
            "period": "MORNING",
            "store_id": 8,
            "offset": 0,
            "limit": 100,
        }
    )

    assert arguments.date == date(2026, 9, 28)
    assert arguments.period == DeliveryPeriod.MORNING
    assert arguments.store_id == 8
    assert arguments.offset == 0
    assert arguments.limit == 100


@pytest.mark.parametrize(
    "payload",
    [
        {"date": "2026-09-28", "limit": 101},
        {"date": "2026-09-28", "limit": 0},
        {"date": "2026-09-28", "offset": -1},
        {"date": "2026-09-28", "store_id": 0},
        {"date": "2026-99-99"},
        {"date": "28/09/2026"},
        {"date": "2026-09-28", "period": "morning"},
        {"date": "2026-09-28", "period": "上午"},
        {"date": "2026-09-28", "drop_database": True},
    ],
)
def test_list_delivery_demands_rejects_unsafe_arguments(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ListDeliveryDemandsArgs.model_validate(payload)


def test_get_vehicle_attendance_accepts_date_and_optional_vehicle() -> None:
    arguments = GetVehicleAttendanceArgs.model_validate(
        {"date": "2026-09-28", "vehicle_id": 12}
    )

    assert arguments.date == date(2026, 9, 28)
    assert arguments.vehicle_id == 12


@pytest.mark.parametrize("vehicle_id", [0, -1, "abc"])
def test_get_vehicle_attendance_rejects_invalid_vehicle_id(vehicle_id) -> None:
    with pytest.raises(ValidationError):
        GetVehicleAttendanceArgs.model_validate(
            {"date": "2026-09-28", "vehicle_id": vehicle_id}
        )


def test_list_dispatch_plans_enforces_date_and_pagination() -> None:
    arguments = ListDispatchPlansArgs.model_validate(
        {"delivery_date": "2026-09-28", "offset": 0, "limit": 100}
    )

    assert arguments.delivery_date == date(2026, 9, 28)
    with pytest.raises(ValidationError):
        ListDispatchPlansArgs.model_validate(
            {"delivery_date": "2026-09-28", "limit": 101}
        )
    with pytest.raises(ValidationError):
        ListDispatchPlansArgs.model_validate(
            {"delivery_date": "2026-09-28", "offset": -1}
        )


@pytest.mark.parametrize(
    "arguments_schema",
    [
        GetDispatchPlanDetailArgs,
        GetUnassignedDemandsArgs,
        ValidateDispatchPlanArgs,
    ],
)
@pytest.mark.parametrize("plan_id", [0, -1, "abc"])
def test_plan_id_tools_reject_non_positive_ids(
    arguments_schema, plan_id
) -> None:
    with pytest.raises(ValidationError):
        arguments_schema.model_validate({"plan_id": plan_id})


@pytest.mark.parametrize(
    "arguments_schema",
    [
        GetDispatchPlanDetailArgs,
        GetUnassignedDemandsArgs,
        ValidateDispatchPlanArgs,
    ],
)
def test_plan_id_tools_accept_positive_id(arguments_schema) -> None:
    assert arguments_schema.model_validate({"plan_id": 1}).plan_id == 1


@pytest.mark.parametrize(
    ("definition", "required"),
    [
        (LIST_DELIVERY_DEMANDS_DEFINITION, ["date"]),
        (GET_VEHICLE_ATTENDANCE_DEFINITION, ["date"]),
        (LIST_DISPATCH_PLANS_DEFINITION, ["delivery_date"]),
        (GET_DISPATCH_PLAN_DETAIL_DEFINITION, ["plan_id"]),
        (GET_UNASSIGNED_DEMANDS_DEFINITION, ["plan_id"]),
        (VALIDATE_DISPATCH_PLAN_DEFINITION, ["plan_id"]),
    ],
)
def test_tool_definitions_are_openai_compatible(definition, required) -> None:
    tool = definition.to_openai_tool()
    parameters = tool["function"]["parameters"]

    assert tool["type"] == "function"
    assert tool["function"]["name"] == definition.name
    assert tool["function"]["description"]
    assert parameters["type"] == "object"
    assert parameters["required"] == required
    assert parameters["additionalProperties"] is False
    assert "$defs" not in parameters
    assert json.loads(json.dumps(tool, ensure_ascii=False)) == tool


def test_period_schema_reuses_delivery_period_enum() -> None:
    parameters = LIST_DELIVERY_DEMANDS_DEFINITION.parameters
    period_schema = parameters["properties"]["period"]
    serialized = json.dumps(period_schema)

    assert "MORNING" in serialized
    assert "AFTERNOON" in serialized
