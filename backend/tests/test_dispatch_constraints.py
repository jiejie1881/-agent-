from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.domain.constraints import (
    LoadConstraint,
    PeriodConstraint,
    RouteConstraint,
    TerrainConstraint,
    VehicleAvailableConstraint,
)
from app.domain.constraints.base import DispatchValidationContext
from app.domain.enums import DeliveryPeriod


@pytest.fixture
def valid_context():
    return DispatchValidationContext(
        dispatch_date=date(2026, 9, 24),
        vehicle_name="粤A10001",
        vehicle_type_name="大包",
        demand_period=DeliveryPeriod.MORNING,
        dispatch_period=DeliveryPeriod.MORNING,
        quantity=Decimal("350"),
        min_load=Decimal("300"),
        max_load=Decimal("420"),
        attendance_exists=True,
        vehicle_available=True,
        store_belongs_to_route=True,
        terrain_configured=True,
        terrain_name="中控",
        terrain_allowed=True,
    )


def test_vehicle_available_constraint_is_independent(valid_context):
    result = VehicleAvailableConstraint().validate(
        replace(valid_context, vehicle_available=False)
    )
    assert result.passed is False
    assert "未出勤" in result.reason


def test_period_constraint_is_independent(valid_context):
    result = PeriodConstraint().validate(
        replace(valid_context, dispatch_period=DeliveryPeriod.AFTERNOON)
    )
    assert result.passed is False
    assert "不能安排" in result.reason


def test_terrain_constraint_is_independent(valid_context):
    result = TerrainConstraint().validate(
        replace(valid_context, terrain_allowed=False)
    )
    assert result.passed is False
    assert "不允许进入" in result.reason


def test_route_constraint_is_independent(valid_context):
    result = RouteConstraint().validate(
        replace(valid_context, store_belongs_to_route=False)
    )
    assert result.passed is False
    assert "不属于" in result.reason


def test_load_constraint_is_independent(valid_context):
    below = LoadConstraint().validate(replace(valid_context, quantity=Decimal("299")))
    above = LoadConstraint().validate(replace(valid_context, quantity=Decimal("421")))
    assert below.passed is False
    assert "低于" in below.reason
    assert above.passed is False
    assert "超过" in above.reason

