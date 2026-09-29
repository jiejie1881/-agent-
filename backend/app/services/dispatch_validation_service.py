from sqlalchemy.orm import Session

from app.domain.constraints.base import DispatchValidationContext
from app.domain.dispatch_validator import DispatchValidationResult, validate_dispatch
from app.domain.exceptions import NotFoundError
from app.repositories.delivery_demand_repository import DeliveryDemandRepository
from app.repositories.route_repository import RouteRepository, RouteTerrainRepository
from app.repositories.store_repository import StoreRouteRepository
from app.repositories.vehicle_attendance_repository import VehicleAttendanceRepository
from app.repositories.vehicle_repository import (
    VehicleRepository,
    VehicleTypeTerrainPermissionRepository,
)
from app.schemas.dispatch_validation import (
    ConstraintValidationResponse,
    DispatchValidationRequest,
    DispatchValidationResponse,
)


class DispatchValidationService:
    def __init__(self, session: Session) -> None:
        self.vehicle_repository = VehicleRepository(session)
        self.demand_repository = DeliveryDemandRepository(session)
        self.route_repository = RouteRepository(session)
        self.attendance_repository = VehicleAttendanceRepository(session)
        self.route_terrain_repository = RouteTerrainRepository(session)
        self.store_route_repository = StoreRouteRepository(session)
        self.permission_repository = VehicleTypeTerrainPermissionRepository(session)

    def validate_dispatch(
        self, data: DispatchValidationRequest
    ) -> DispatchValidationResponse:
        result = self.validate_result(data)
        return DispatchValidationResponse(
            is_valid=result.is_valid,
            result="合法" if result.is_valid else "不合法",
            failure_reasons=result.failure_reasons,
            constraints=[
                ConstraintValidationResponse(
                    constraint=item.constraint,
                    passed=item.passed,
                    reason=item.reason,
                    code=item.code,
                )
                for item in result.constraint_results
            ],
        )

    def validate_result(
        self, data: DispatchValidationRequest
    ) -> DispatchValidationResult:
        vehicle = self.vehicle_repository.get(data.vehicle_id)
        if vehicle is None:
            raise NotFoundError("车辆不存在")
        demand = self.demand_repository.get(data.delivery_demand_id)
        if demand is None:
            raise NotFoundError("门店配送需求不存在")
        route = self.route_repository.get(data.route_id)
        if route is None:
            raise NotFoundError("线路不存在")

        attendance = self.attendance_repository.get_by_date_vehicle(
            demand.date, vehicle.id
        )
        route_terrain = self.route_terrain_repository.get_effective(
            route.id, demand.date
        )
        store_route = self.store_route_repository.get_link(
            demand.store_id, route.id
        )
        terrain_permission = None
        if route_terrain is not None:
            terrain_permission = self.permission_repository.get_permission(
                vehicle.vehicle_type_id, route_terrain.terrain_id
            )

        context = DispatchValidationContext(
            dispatch_date=demand.date,
            vehicle_name=vehicle.plate_number,
            vehicle_type_name=vehicle.vehicle_type.name,
            demand_period=demand.period,
            dispatch_period=data.period,
            quantity=data.quantity,
            min_load=vehicle.vehicle_type.min_load,
            max_load=vehicle.vehicle_type.max_load,
            attendance_exists=attendance is not None,
            vehicle_available=attendance.available if attendance else False,
            store_belongs_to_route=store_route is not None,
            terrain_configured=route_terrain is not None,
            terrain_name=(route_terrain.terrain.name if route_terrain else None),
            terrain_allowed=terrain_permission is not None,
        )
        return validate_dispatch(context)
