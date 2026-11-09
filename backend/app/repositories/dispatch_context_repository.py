"""Read-only, complete snapshot queries with explicit safe-field projection."""
from sqlalchemy import or_, select

from app.domain.enums import UserRole
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchOrder, DispatchOrderDetail, DispatchPlan
from app.models.driver_scheduling import (
    DriverAttendance,
    DriverAttendanceRule,
    DriverLeave,
    DriverSchedule,
    DriverSubstitution,
)
from app.models.route import Route, RouteTerrainConfig
from app.models.store import Store, StoreRoute
from app.models.terrain import Terrain
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleType, VehicleTypeTerrainPermission
from app.models.vehicle_attendance import VehicleAttendance


class DispatchContextRepository:
    def __init__(self, session):
        self.session = session

    def load(self, day):
        specifications = {
            "demands": (DeliveryDemand, ("id", "date", "store_id", "period", "quantity", "priority", "status"), DeliveryDemand.date == day),
            "stores": (Store, ("id", "code", "name", "is_active"), None),
            "store_routes": (StoreRoute, ("id", "store_id", "route_id"), None),
            "routes": (Route, ("id", "code", "name", "is_active"), None),
            "terrains": (Terrain, ("id", "code", "name"), None),
            "terrain_configs": (RouteTerrainConfig, ("id", "route_id", "terrain_id", "effective_date", "updated_at"), RouteTerrainConfig.effective_date <= day),
            "vehicles": (Vehicle, ("id", "code", "plate_number", "vehicle_type_id", "driver_user_id", "is_active", "operating_status", "rated_load", "daily_trip_limit", "allowed_route_ids"), None),
            "vehicle_types": (VehicleType, ("id", "code", "name", "min_load", "max_load", "is_active"), None),
            "permissions": (VehicleTypeTerrainPermission, ("id", "vehicle_type_id", "terrain_id"), None),
            "vehicle_attendances": (VehicleAttendance, ("id", "vehicle_id", "available"), VehicleAttendance.date == day),
            # Refresh referenced users even if their role changed away from
            # DRIVER; otherwise resolve() could see an old identity-map role.
            "drivers": (User, ("id", "username", "display_name", "role", "is_active"), or_(
                User.role == UserRole.DRIVER,
                User.id.in_(select(Vehicle.driver_user_id)),
                User.id.in_(select(DriverSchedule.driver_id).where(DriverSchedule.date == day)))),
            "driver_attendances": (DriverAttendance, ("id", "driver_id", "period", "available", "override_enabled"), DriverAttendance.date == day),
            "driver_rules": (DriverAttendanceRule, ("id", "driver_id", "period", "available", "effective_date"), DriverAttendanceRule.effective_date <= day),
            "schedules": (DriverSchedule, ("id", "vehicle_id", "driver_id", "original_driver_id", "period", "kind", "status"), DriverSchedule.date == day),
            "leaves": (DriverLeave, ("id", "driver_id", "start_date", "end_date", "period", "status"), (DriverLeave.start_date <= day) & (DriverLeave.end_date >= day)),
            "substitutions": (DriverSubstitution, ("id", "vehicle_id", "original_driver_id", "substitute_driver_id", "period", "status", "active_vehicle_id", "active_driver_id"), DriverSubstitution.date == day),
            "plans": (DispatchPlan, ("id", "delivery_date", "version", "status"), DispatchPlan.delivery_date == day),
        }
        result = {}
        for name, (model, fields, condition) in specifications.items():
            query = select(model).order_by(model.id).execution_options(populate_existing=True)
            if condition is not None:
                query = query.where(condition)
            result[name] = [{field: getattr(row, field) for field in fields}
                            for row in self.session.scalars(query)]
        plan_ids = [p["id"] for p in result["plans"]]
        orders = list(self.session.scalars(select(DispatchOrder).where(
            DispatchOrder.plan_id.in_(plan_ids)).order_by(DispatchOrder.id)
            .execution_options(populate_existing=True)))
        result["orders"] = [{f: getattr(row, f) for f in
                             ("id", "plan_id", "vehicle_id", "actual_driver_id", "period", "trip_no", "route_id", "total_load")}
                            for row in orders]
        result["details"] = [{f: getattr(row, f) for f in
                              ("id", "dispatch_order_id", "delivery_demand_id", "quantity", "delivery_status")}
                             for row in self.session.scalars(select(DispatchOrderDetail).where(
                                 DispatchOrderDetail.dispatch_order_id.in_([o.id for o in orders]))
                                 .order_by(DispatchOrderDetail.id).execution_options(populate_existing=True))]
        return result
