from sqlalchemy.orm import Session
from dataclasses import replace
from sqlalchemy.exc import IntegrityError
import logging

from app.dispatch_engine.dispatch_engine import DispatchEngine
from app.domain.enums import DeliveryDemandStatus, DispatchPlanStatus, DeliveryPeriod
from app.domain.exceptions import BusinessError
from app.dispatch_engine.models import DispatchEngineResult, UnassignedDemand
from app.services.driver_scheduling_service import DriverSchedulingService
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
        scheduling = DriverSchedulingService(self.session)
        from app.services.driver_leave_service import DriverLeaveService
        DriverLeaveService(self.session).lock_resources()
        engine_input = self.repository.load(data.date)
        trips, unassigned = [], []
        for period in DeliveryPeriod:
            eligible = []
            excluded = []
            for vehicle in engine_input.vehicles:
                try:
                    scheduling.resolve(data.date, period.value, vehicle.id)
                    eligible.append(vehicle)
                except BusinessError as exc:
                    excluded.append(f"车辆#{vehicle.id}: {exc.code}: {exc.message}")
                    continue
            demands = tuple(d for d in engine_input.demands if d.period == period)
            partial = self.engine.dispatch(replace(engine_input, demands=demands, vehicles=tuple(eligible)))
            trips.extend(partial.trips)
            if not eligible and engine_input.vehicles:
                unassigned.extend(UnassignedDemand(d, ("所有出勤候选车辆均未通过司机可用性校验", *excluded)) for d in demands)
            else:
                unassigned.extend(
                    UnassignedDemand(item.demand, (*item.reasons,
                        "另有车辆因司机可用性被排除；下列记录不代表这些车辆满足该需求的其他运输约束", *excluded))
                    if excluded else item
                    for item in partial.unassigned_demands
                )
        result = DispatchEngineResult(data.date, tuple(trips), tuple(unassigned))
        try:
            version = self.plan_repository.next_version(result.dispatch_date)
            plan = self.plan_repository.save_result(
                result,
                version=version,
                status=DispatchPlanStatus.DRAFT,
            )
            for order in plan.orders:
                driver = scheduling.resolve(data.date, order.period.value, order.vehicle_id)
                order.actual_driver_id = driver.id
                order.driver_username_snapshot = driver.username
                order.driver_name_snapshot = driver.display_name
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
            from app.services.dispatch_quality_service import DispatchQualityService, freeze_scope
            quality_warning = None
            # 评分是附加报告，不允许失败回滚已合法生成的派车；独立保存点隔离。
            try:
                with self.session.begin_nested():
                    DispatchQualityService(self.session).generate(plan.id, actor, freeze_scope(engine_input.demands), commit=False)
            except Exception:
                quality_warning = '方案已保存，但质量报告生成失败，请到质量报告页面重试'
                logging.getLogger(__name__).warning('QUALITY_REPORT_FAILED plan_id=%s', plan.id)
            self.session.commit()
        except BusinessError:
            self.session.rollback()
            raise
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("派车方案版本生成冲突，请重新生成") from exc
        return AutoDispatchResponse(
            plan_id=plan.id,
            quality_warning=quality_warning,
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
                            cargo_category_code=item.demand.cargo_category_code,
                            cargo_category_name=item.demand.cargo_category_name,
                            priority=item.demand.priority,
                            requires_temperature_control=item.demand.requires_temperature_control,
                            min_temperature=item.demand.min_temperature,
                            max_temperature=item.demand.max_temperature,
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
                    cargo_category_code=item.demand.cargo_category_code,
                    cargo_category_name=item.demand.cargo_category_name,
                    priority=item.demand.priority,
                    requires_temperature_control=item.demand.requires_temperature_control,
                    min_temperature=item.demand.min_temperature,
                    max_temperature=item.demand.max_temperature,
                )
                for item in result.unassigned_demands
            ],
        )
