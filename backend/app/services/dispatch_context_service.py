"""Materialize a detached planning context; never generate or persist a plan."""
from datetime import UTC, date, datetime

from pydantic import TypeAdapter

from app.domain.enums import DeliveryPeriod
from app.domain.exceptions import BusinessError
from app.repositories.dispatch_context_repository import DispatchContextRepository
from app.repositories.dispatch_engine_repository import DispatchEngineRepository
from app.schemas.dispatch_candidate import (
    ContextDemand,
    ContextRoute,
    ContextShift,
    ContextStore,
    ContextVehicle,
    DispatchContext,
)
from app.services.driver_scheduling_service import DriverSchedulingService


class DispatchContextService:
    def __init__(self, session):
        self.session = session
        self.repository = DispatchContextRepository(session)
        self.engine_repository = DispatchEngineRepository(session)
        self.scheduling = DriverSchedulingService(session)

    def load(self, day) -> DispatchContext:
        day = TypeAdapter(date).validate_python(day)
        # Autoflush could turn a read into a write. Require a clean unit of work
        # rather than commit/rollback or discard the caller's pending changes.
        if self.session.new or self.session.dirty or self.session.deleted:
            raise ValueError("调度上下文必须从无待写入修改的 Session 加载")
        with self.session.no_autoflush:
            facts = self.repository.load(day)
            engine = self.engine_repository.load(day)
            eligible = {d.id for d in engine.demands}
            types = {v["id"]: v for v in facts["vehicle_types"]}
            attendance = {a["vehicle_id"]: a for a in facts["vehicle_attendances"]}
            vehicles = []
            shifts = []
            for v in facts["vehicles"]:
                t, a = types[v["vehicle_type_id"]], attendance.get(v["id"])
                vehicles.append(ContextVehicle(
                    id=v["id"], code=v["code"], plate_number=v["plate_number"],
                    vehicle_type_id=t["id"], vehicle_type_code=t["code"],
                    vehicle_type_name=t["name"], min_load=t["min_load"], max_load=min(t['max_load'],v['rated_load']) if v['rated_load'] else t['max_load'],
                    is_active=v["is_active"], type_active=t["is_active"],
                    attendance_exists=a is not None, available=bool(a and a["available"]),
                    default_driver_id=v["driver_user_id"], operating_status=v['operating_status'],
                    daily_trip_limit=v['daily_trip_limit'], allowed_route_ids=v['allowed_route_ids']))
                for period in DeliveryPeriod:
                    try:
                        driver = self.scheduling.resolve(day, period.value, v["id"], for_update=False)
                        shifts.append(ContextShift(vehicle_id=v["id"], period=period,
                                                   driver_id=driver.id, available=True))
                    except BusinessError as exc:
                        shifts.append(ContextShift(vehicle_id=v["id"], period=period,
                            driver_id=None, available=False, violation_code=exc.code, message=exc.message))
            # A second projection detects changes during capture on databases
            # without a repeatable-read snapshot. It does not replace write locks.
            adapter = TypeAdapter(dict)
            records = adapter.dump_python(facts, mode="json")
            if records != adapter.dump_python(self.repository.load(day), mode="json"):
                raise ValueError("调度数据在快照采集期间变化，请重新加载")
            effective_terrain = {}
            terrains = {t["id"]: t["name"] for t in facts["terrains"]}
            for config in sorted(facts["terrain_configs"], key=lambda c:
                                 (c["effective_date"], c["updated_at"], c["id"]), reverse=True):
                effective_terrain.setdefault(config["route_id"], config["terrain_id"])
            context = DispatchContext(
                delivery_date=day, captured_at=datetime.now(UTC), snapshot_version="",
                demands=tuple(ContextDemand(**d, schedulable=d["id"] in eligible) for d in facts["demands"]),
                stores=tuple(ContextStore(id=s["id"], code=s["code"], name=s["name"], is_active=s['is_active'],
                    route_ids=tuple(sorted(link["route_id"] for link in facts["store_routes"]
                                           if link["store_id"] == s["id"]))) for s in facts["stores"]),
                routes=tuple(ContextRoute(id=r["id"], code=r["code"], name=r["name"], is_active=r['is_active'],
                    terrain_id=effective_terrain.get(r["id"]),
                    terrain_name=terrains.get(effective_terrain.get(r["id"])))
                    for r in facts["routes"]),
                vehicles=tuple(vehicles), shifts=tuple(shifts),
                terrain_permissions=tuple(sorted((p["vehicle_type_id"], p["terrain_id"])
                                                 for p in facts["permissions"])), resource_records=records)
            return context.model_copy(update={"snapshot_version": context.fingerprint()})
