from collections import defaultdict
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.domain.enums import DeliveryDemandStatus, DispatchPlanStatus
from app.dispatch_engine.models import (
    DispatchEngineInput,
    EngineDemand,
    EngineRoute,
    EngineVehicle,
)
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchOrder, DispatchOrderDetail, DispatchPlan
from app.models.route import Route, RouteTerrainConfig
from app.models.store import StoreRoute
from app.models.vehicle import Vehicle, VehicleType, VehicleTypeTerrainPermission
from app.models.vehicle_attendance import VehicleAttendance


class DispatchEngineRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def load(self, dispatch_date: date) -> DispatchEngineInput:
        demands = self._load_demands(dispatch_date)
        vehicles = self._load_vehicles(dispatch_date)
        store_route_ids = self._load_store_routes(
            {demand.store_id for demand in demands}
        )
        routes = self._load_effective_routes(
            {route_id for ids in store_route_ids.values() for route_id in ids},
            dispatch_date,
        )
        permissions = self._load_permissions(
            {vehicle.vehicle_type_id for vehicle in vehicles},
            {route.terrain_id for route in routes.values()},
        )
        return DispatchEngineInput(
            dispatch_date=dispatch_date,
            demands=tuple(demands),
            vehicles=tuple(vehicles),
            routes=routes,
            store_route_ids=store_route_ids,
            permissions=permissions,
        )

    def _load_demands(self, dispatch_date: date) -> list[EngineDemand]:
        assigned_to_draft = (
            select(DispatchOrderDetail.id)
            .join(
                DispatchOrder,
                DispatchOrder.id == DispatchOrderDetail.dispatch_order_id,
            )
            .join(DispatchPlan, DispatchPlan.id == DispatchOrder.plan_id)
            .where(
                DispatchOrderDetail.delivery_demand_id == DeliveryDemand.id,
                DispatchPlan.delivery_date == dispatch_date,
                DispatchPlan.status == DispatchPlanStatus.DRAFT,
            )
            .exists()
        )
        statement = (
            select(DeliveryDemand)
            .options(joinedload(DeliveryDemand.store))
            .where(
                DeliveryDemand.date == dispatch_date,
                or_(
                    DeliveryDemand.status == DeliveryDemandStatus.PENDING,
                    and_(
                        DeliveryDemand.status == DeliveryDemandStatus.PLANNED,
                        assigned_to_draft,
                    ),
                ),
            )
            .order_by(DeliveryDemand.period, DeliveryDemand.id)
        )
        return [
            EngineDemand(
                id=demand.id,
                date=demand.date,
                store_id=demand.store_id,
                store_code=demand.store.code,
                store_name=demand.store.name,
                period=demand.period,
                quantity=demand.quantity,
            )
            for demand in self.session.scalars(statement)
        ]

    def _load_vehicles(self, dispatch_date: date) -> list[EngineVehicle]:
        statement = (
            select(Vehicle)
            .join(VehicleAttendance, VehicleAttendance.vehicle_id == Vehicle.id)
            .options(joinedload(Vehicle.vehicle_type))
            .where(
                VehicleAttendance.date == dispatch_date,
                VehicleAttendance.available.is_(True),
            )
            .order_by(Vehicle.id)
        )
        return [
            EngineVehicle(
                id=vehicle.id,
                code=vehicle.code,
                plate_number=vehicle.plate_number,
                vehicle_type_id=vehicle.vehicle_type_id,
                vehicle_type_code=vehicle.vehicle_type.code,
                vehicle_type_name=vehicle.vehicle_type.name,
                min_load=vehicle.vehicle_type.min_load,
                max_load=vehicle.vehicle_type.max_load,
            )
            for vehicle in self.session.scalars(statement)
        ]

    def _load_store_routes(
        self, store_ids: set[int]
    ) -> dict[int, set[int]]:
        if not store_ids:
            return {}
        statement = select(StoreRoute).where(StoreRoute.store_id.in_(store_ids))
        result: dict[int, set[int]] = defaultdict(set)
        for link in self.session.scalars(statement):
            result[link.store_id].add(link.route_id)
        return dict(result)

    def _load_effective_routes(
        self, route_ids: set[int], dispatch_date: date
    ) -> dict[int, EngineRoute]:
        if not route_ids:
            return {}
        statement = (
            select(RouteTerrainConfig)
            .options(
                joinedload(RouteTerrainConfig.route),
                joinedload(RouteTerrainConfig.terrain),
            )
            .where(
                RouteTerrainConfig.route_id.in_(route_ids),
                RouteTerrainConfig.effective_date <= dispatch_date,
            )
            .order_by(
                RouteTerrainConfig.route_id,
                RouteTerrainConfig.effective_date.desc(),
                RouteTerrainConfig.updated_at.desc(),
            )
        )
        routes: dict[int, EngineRoute] = {}
        for config in self.session.scalars(statement):
            if config.route_id in routes:
                continue
            routes[config.route_id] = EngineRoute(
                id=config.route.id,
                code=config.route.code,
                name=config.route.name,
                terrain_id=config.terrain_id,
                terrain_name=config.terrain.name,
            )
        return routes

    def _load_permissions(
        self, vehicle_type_ids: set[int], terrain_ids: set[int]
    ) -> set[tuple[int, int]]:
        if not vehicle_type_ids or not terrain_ids:
            return set()
        statement = select(VehicleTypeTerrainPermission).where(
            VehicleTypeTerrainPermission.vehicle_type_id.in_(vehicle_type_ids),
            VehicleTypeTerrainPermission.terrain_id.in_(terrain_ids),
        )
        return {
            (permission.vehicle_type_id, permission.terrain_id)
            for permission in self.session.scalars(statement)
        }
