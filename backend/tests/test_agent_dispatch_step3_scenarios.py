"""Anonymous, in-memory acceptance scenes for the shadow dispatch workflow."""
from copy import deepcopy

import pytest
from sqlalchemy import select

from app.domain.enums import DeliveryDemandStatus, DeliveryPeriod, UserRole
from app.models.delivery_demand import DeliveryDemand
from app.models.driver_scheduling import (
    DriverAttendance,
    DriverLeave,
    DriverSchedule,
    DriverSubstitution,
)
from app.models.store import Store, StoreRoute
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleTypeTerrainPermission
from app.models.vehicle_attendance import VehicleAttendance
from app.schemas.agent_dispatch import ShadowDispatchRequest
from tests import test_agent_dispatch_foundation as foundation
from tests.test_agent_dispatch_shadow import FakeModel, execute, table_contents


@pytest.fixture
def resources(session):
    return foundation.resources.__wrapped__(session)


def _unassigned(demand_id, explanation):
    return {"demand_id": demand_id, "explanation": explanation}


def _add_demand(session, resources, *, quantity, period=DeliveryPeriod.MORNING):
    store_number = len(session.scalars(select(Store)).all()) + 1
    store = Store(
        code=f"ANON-S{store_number}",
        name=f"匿名演示门店{store_number}",
    )
    session.add(store)
    session.flush()
    session.add(StoreRoute(store_id=store.id, route_id=resources["route"].id))
    demand = DeliveryDemand(
        date=foundation.DAY,
        store_id=store.id,
        period=period,
        quantity=quantity,
        status=DeliveryDemandStatus.PENDING,
    )
    session.add(demand)
    session.flush()
    return demand


def _scene(name, session, resources):
    """Return fixed model outputs and expected deterministic outcomes."""
    driver = resources["driver"]
    vehicle = resources["vehicle"]
    demand = resources["demand"]

    if name == "overweight":
        demand.quantity = 600
    elif name == "leave_without_substitute":
        session.add(DriverLeave(
            driver_id=driver.id, start_date=foundation.DAY, end_date=foundation.DAY,
            period="MORNING", reason="anonymous test", status="APPROVED",
            actor_id=driver.id,
        ))
    elif name == "confirmed_substitute":
        leave = DriverLeave(
            driver_id=driver.id, start_date=foundation.DAY, end_date=foundation.DAY,
            period="MORNING", reason="anonymous test", status="APPROVED",
            actor_id=driver.id,
        )
        session.add(leave)
        session.flush()
        substitute = resources["standby"]
        session.add_all([
            DriverSchedule(
                date=foundation.DAY, period="MORNING", vehicle_id=vehicle.id,
                driver_id=substitute.id, original_driver_id=driver.id,
                kind="SUBSTITUTE", status="ACTIVE", actor_id=driver.id,
            ),
            DriverSubstitution(
                leave_request_id=leave.id, date=foundation.DAY, period="MORNING",
                vehicle_id=vehicle.id, original_driver_id=driver.id,
                substitute_driver_id=substitute.id, status="CONFIRMED",
                active_vehicle_id=vehicle.id, active_driver_id=substitute.id,
            ),
        ])
    elif name == "route_mismatch":
        session.delete(session.scalar(select(StoreRoute)))
    elif name == "terrain_mismatch":
        session.delete(session.scalar(select(VehicleTypeTerrainPermission)))
    elif name == "period_mismatch":
        extra = _add_demand(session, resources, quantity=200, period=DeliveryPeriod.AFTERNOON)
        session.add(DriverAttendance(
            driver_id=driver.id, date=foundation.DAY, period="AFTERNOON",
            available=True, actor_id=driver.id,
        ))
    elif name == "multi_vehicle_multi_trip":
        extra = _add_demand(session, resources, quantity=200)
        third = _add_demand(session, resources, quantity=200)
        second_driver = User(
            username="anonymous-driver-two", password_hash="offline-unusable-hash",
            role=UserRole.DRIVER, is_active=True,
        )
        session.add(second_driver)
        session.flush()
        second_vehicle = Vehicle(
            code="ANON-V2", plate_number="湘A00002",
            vehicle_type_id=resources["kind"].id,
            driver_user_id=second_driver.id, is_active=True,
        )
        session.add(second_vehicle)
        session.flush()
        session.add_all([
            VehicleAttendance(date=foundation.DAY, vehicle_id=second_vehicle.id, available=True),
            DriverAttendance(
                driver_id=second_driver.id, date=foundation.DAY, period="MORNING",
                available=True, actor_id=second_driver.id,
            ),
        ])
    elif name == "partial_unassigned":
        extra = _add_demand(session, resources, quantity=600)
    elif name == "no_full_solution":
        demand.quantity = 600
        extra = _add_demand(session, resources, quantity=700)
    elif name != "all_assigned":
        raise AssertionError(f"unknown anonymous scene: {name}")

    session.commit()
    context = foundation.context(session)
    valid = foundation.candidate(context, resources)
    outputs = [valid]
    expected_code = None
    assigned, unassigned, used_vehicles, trip_count = 1, 0, 1, 1

    if name in {"overweight", "leave_without_substitute", "route_mismatch", "terrain_mismatch"}:
        expected_code = {
            "overweight": "OVERLOAD",
            "leave_without_substitute": "DRIVER_ON_LEAVE_NO_CONFIRMED_SUBSTITUTE",
            "route_mismatch": "ROUTE_NOT_ALLOWED",
            "terrain_mismatch": "TERRAIN_NOT_ALLOWED",
        }[name]
        repaired = deepcopy(valid)
        repaired["candidate_id"] = "repaired-anonymous"
        repaired["trips"] = []
        repaired["unassigned"] = [_unassigned(demand.id, "本次无合法车辆与司机组合")]
        outputs.append(repaired)
        assigned, unassigned, used_vehicles, trip_count = 0, 1, 0, 0
    elif name == "confirmed_substitute":
        valid["trips"][0]["driver_id"] = resources["standby"].id
    elif name == "period_mismatch":
        valid["trips"][0]["demand_ids"].append(extra.id)
        expected_code = "PERIOD_MISMATCH"
        repaired = deepcopy(valid)
        repaired["candidate_id"] = "repaired-period"
        repaired["trips"][0]["demand_ids"] = [demand.id]
        repaired["trips"].append({
            "vehicle_id": vehicle.id, "driver_id": driver.id,
            "route_id": resources["route"].id, "period": "AFTERNOON",
            "trip_no": 1, "demand_ids": [extra.id],
        })
        outputs.append(repaired)
        assigned, trip_count = 2, 2
    elif name == "multi_vehicle_multi_trip":
        valid["trips"].extend([
            {
                "vehicle_id": vehicle.id, "driver_id": driver.id,
                "route_id": resources["route"].id, "period": "MORNING",
                "trip_no": 2, "demand_ids": [extra.id],
            },
            {
                "vehicle_id": second_vehicle.id, "driver_id": second_driver.id,
                "route_id": resources["route"].id, "period": "MORNING",
                "trip_no": 1, "demand_ids": [third.id],
            },
        ])
        assigned, used_vehicles, trip_count = 3, 2, 3
    elif name == "partial_unassigned":
        valid["unassigned"] = [_unassigned(extra.id, "600 kg 超过车型最大载重 500 kg")]
        unassigned = 1
    elif name == "no_full_solution":
        valid["trips"] = []
        valid["unassigned"] = [
            _unassigned(demand.id, "600 kg 超过车型最大载重 500 kg"),
            _unassigned(extra.id, "700 kg 超过车型最大载重 500 kg"),
        ]
        assigned, unassigned, used_vehicles, trip_count = 0, 2, 0, 0

    return context, outputs, expected_code, (assigned, unassigned, used_vehicles, trip_count)


@pytest.mark.parametrize("name", [
    "all_assigned",
    "overweight",
    "leave_without_substitute",
    "confirmed_substitute",
    "route_mismatch",
    "terrain_mismatch",
    "period_mismatch",
    "multi_vehicle_multi_trip",
    "partial_unassigned",
    "no_full_solution",
])
def test_anonymous_shadow_scene(session, resources, name):
    context, outputs, expected_code, expected_metrics = _scene(name, session, resources)
    before = table_contents(session)
    model = FakeModel(outputs)
    result = execute(
        session, model,
        request=ShadowDispatchRequest(delivery_date=foundation.DAY, compare_greedy=True),
    )
    assert result.status == "SUCCESS", (name, result.reason_code)
    assert result.validation is not None and result.validation.is_valid
    assert result.freshness_checked and not result.stale_context
    assert result.snapshot_version == context.snapshot_version
    assert result.generation_count == len(outputs)
    assert result.revision_count == len(outputs) - 1
    assert result.validation_count == len(outputs)
    assert len(result.attempts) == len(outputs)
    if expected_code:
        assert not result.attempts[0].validation.is_valid
        assert expected_code in {
            item.violation_code for item in result.attempts[0].validation.violations
        }
        assert result.attempts[-1].validation.is_valid
    assert (
        result.metrics.assigned_count,
        result.metrics.unassigned_count,
        result.metrics.used_vehicles,
        len(result.metrics.trips),
    ) == expected_metrics
    assert result.comparison is not None and result.comparison.status == "PASS"
    assert result.comparison.validation is not None and result.comparison.validation.is_valid
    assert result.comparison.metrics.total_demands == result.metrics.total_demands
    prompt = model.calls[0][0][1].content.lower()
    assert all(secret not in prompt for secret in ("password_hash", "api_key", "jwt_secret"))
    assert table_contents(session) == before
    assert not session.new and not session.dirty and not session.deleted
