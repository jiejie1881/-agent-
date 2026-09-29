from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.dispatch_engine.dispatch_engine import DispatchEngine
from app.domain.enums import DeliveryDemandStatus, DispatchPlanStatus
from app.domain.exceptions import ConflictError
from app.repositories.dispatch_engine_repository import DispatchEngineRepository
from app.repositories.dispatch_plan_repository import DispatchPlanRepository
from app.schemas.auto_dispatch import (
    AutoDispatchRequest,
    AutoDispatchResponse,
    DispatchRouteResponse,
    DispatchStoreResponse,
    DispatchTripResponse,
    DispatchVehicleResponse,
    UnassignedDemandResponse,
)
from app.services.delivery_demand_status_service import DeliveryDemandStatusService
from app.models.user import User
from app.services.audit_log_service import AuditAction, AuditLogService


class AutoDispatchService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = DispatchEngineRepository(session)
        self.plan_repository = DispatchPlanRepository(session)
        self.demand_status_service = DeliveryDemandStatusService(session)
        self.engine = DispatchEngine()

    def dispatch(self, data: AutoDispatchRequest, actor: User) -> AutoDispatchResponse:
        engine_input = self.repository.load(data.date)
        result = self.engine.dispatch(engine_input)
        try:
            version = self.plan_repository.next_version(result.dispatch_date)
            plan = self.plan_repository.save_result(
                result,
                version=version,
                status=DispatchPlanStatus.DRAFT,
            )
            assigned_demand_ids = {
                item.demand.id
                for trip in result.trips
                for item in trip.demands
            }
            self.demand_status_service.transition_many(
                assigned_demand_ids,
                DeliveryDemandStatus.PLANNED,
                allowed_current={
                    DeliveryDemandStatus.PENDING,
                    DeliveryDemandStatus.PLANNED,
                },
            )
            AuditLogService(self.session).add(
                actor,
                AuditAction.AUTO_DISPATCH_GENERATED,
                "DispatchPlan",
                plan.id,
                {
                    "delivery_date": result.dispatch_date,
                    "version": plan.version,
                    "order_count": len(result.trips),
                    "assigned_demand_count": len(assigned_demand_ids),
                    "unassigned_demand_count": len(result.unassigned_demands),
                },
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("派车方案版本生成冲突，请重新生成") from exc
        return AutoDispatchResponse(
            plan_id=plan.id,
            date=result.dispatch_date,
            version=plan.version,
            status=plan.status,
            trips=[
                DispatchTripResponse(
                    vehicle=DispatchVehicleResponse(
                        id=trip.vehicle.id,
                        code=trip.vehicle.code,
                        plate_number=trip.vehicle.plate_number,
                        vehicle_type_id=trip.vehicle.vehicle_type_id,
                        vehicle_type_code=trip.vehicle.vehicle_type_code,
                        vehicle_type_name=trip.vehicle.vehicle_type_name,
                    ),
                    period=trip.period,
                    trip_no=trip.trip_no,
                    route=DispatchRouteResponse(
                        id=trip.route.id,
                        code=trip.route.code,
                        name=trip.route.name,
                        terrain_id=trip.route.terrain_id,
                        terrain_name=trip.route.terrain_name,
                    ),
                    stores=[
                        DispatchStoreResponse(
                            demand_id=item.demand.id,
                            store_id=item.demand.store_id,
                            store_code=item.demand.store_code,
                            store_name=item.demand.store_name,
                            quantity=item.quantity,
                        )
                        for item in trip.demands
                    ],
                    total_load=trip.total_load,
                )
                for trip in result.trips
            ],
            unassigned_demands=[
                UnassignedDemandResponse(
                    demand_id=item.demand.id,
                    store_id=item.demand.store_id,
                    store_code=item.demand.store_code,
                    store_name=item.demand.store_name,
                    period=item.demand.period,
                    quantity=item.demand.quantity,
                    reasons=list(item.reasons),
                )
                for item in result.unassigned_demands
            ],
        )
