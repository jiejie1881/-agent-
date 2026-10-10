from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.constraints import LoadConstraint
from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryStopStatus,
    DispatchPlanStatus,
)
from app.domain.exceptions import (
    BusinessError,
    ConflictError,
    DispatchAdjustmentError,
    DispatchAdjustmentValidationError,
    DispatchPlanValidationError,
    NotFoundError,
)
from app.models.dispatch_plan import DispatchOrder, DispatchPlan
from app.models.user import User
from app.repositories.dispatch_plan_repository import DispatchPlanRepository
from app.schemas.auto_dispatch import DispatchVehicleResponse
from app.schemas.dispatch_validation import DispatchValidationRequest
from app.schemas.driver import DeliveryProofResponse
from app.schemas.dispatch_plan import (
    DispatchDemandMoveRequest,
    DispatchPlanDetailResponse,
    DispatchPlanSummaryResponse,
    DispatchPlanValidationResponse,
    PersistedDispatchOrderDetailResponse,
    PersistedDispatchOrderResponse,
    PersistedDispatchRouteResponse,
    PersistedUnassignedDemandResponse,
)
from app.services.delivery_demand_status_service import DeliveryDemandStatusService
from app.services.dispatch_validation_service import DispatchValidationService
from app.services.dispatch_plan_publication_validator import (
    DispatchPlanPublicationValidator,
)
from app.services.audit_log_service import AuditAction, AuditLogService


class DispatchPlanService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = DispatchPlanRepository(session)
        self.demand_status_service = DeliveryDemandStatusService(session)
        self.dispatch_validation_service = DispatchValidationService(session)
        self.publication_validator = DispatchPlanPublicationValidator(
            self.dispatch_validation_service
        )
        self.load_constraint = LoadConstraint()

    def list(
        self, delivery_date: date | None, offset: int, limit: int
    ) -> list[DispatchPlanSummaryResponse]:
        return [
            self._to_summary(plan)
            for plan in self.repository.list(delivery_date, offset, limit)
        ]

    def get(self, plan_id: int) -> DispatchPlanDetailResponse:
        return self._to_detail(self._get_model(plan_id))

    def get_by_version(
        self, delivery_date: date, version: int
    ) -> DispatchPlanDetailResponse:
        plan = self.repository.get_by_date_version(delivery_date, version)
        if plan is None:
            raise NotFoundError("指定日期和版本的派车方案不存在")
        return self._to_detail(plan)

    def validate_plan(self, plan_id: int) -> DispatchPlanValidationResponse:
        plan = self._get_model(plan_id)
        issues = self.publication_validator.validate(plan)
        return DispatchPlanValidationResponse(
            plan_id=plan.id,
            valid=not issues,
            issues=issues,
        )

    def publish(self, plan_id: int, actor: User) -> DispatchPlanDetailResponse:
        try:
            from app.services.driver_leave_service import DriverLeaveService
            DriverLeaveService(self.session).lock_resources()
            plan = self.repository.get_for_update(plan_id)
            if plan is None:
                raise NotFoundError("派车方案不存在")
            if plan.status == DispatchPlanStatus.PUBLISHED:
                return self._to_detail(plan)
            if plan.status != DispatchPlanStatus.DRAFT:
                raise ConflictError("只有DRAFT方案可以发布")

            validation_issues = self.publication_validator.validate(plan)
            if validation_issues:
                raise DispatchPlanValidationError(validation_issues)

            previous = self.repository.get_published_by_date(
                plan.delivery_date, exclude_plan_id=plan.id
            )
            new_demand_ids = self._assigned_demand_ids(plan)
            previous_demand_ids = (
                self._assigned_demand_ids(previous) if previous is not None else set()
            )
            previous_only_ids = previous_demand_ids - new_demand_ids
            draft_owned_previous_ids = (
                self.repository.assigned_demand_ids_in_draft_plans(
                    plan.delivery_date,
                    previous_only_ids,
                )
            )
            self.demand_status_service.transition_many(
                previous_only_ids,
                DeliveryDemandStatus.PENDING,
                allowed_current={DeliveryDemandStatus.PUBLISHED},
            )
            self.demand_status_service.transition_many(
                draft_owned_previous_ids,
                DeliveryDemandStatus.PLANNED,
                allowed_current={DeliveryDemandStatus.PENDING},
            )
            self.demand_status_service.transition_many(
                new_demand_ids - previous_demand_ids,
                DeliveryDemandStatus.PUBLISHED,
                allowed_current={DeliveryDemandStatus.PLANNED},
            )
            if previous is not None:
                self.repository.set_status(previous, DispatchPlanStatus.CANCELLED)
            self.repository.set_status(plan, DispatchPlanStatus.PUBLISHED)
            AuditLogService(self.session).add(
                actor,
                AuditAction.DISPATCH_PLAN_PUBLISHED,
                "DispatchPlan",
                plan.id,
                {
                    "before_status": DispatchPlanStatus.DRAFT.value,
                    "after_status": DispatchPlanStatus.PUBLISHED.value,
                    "version": plan.version,
                    "replaced_plan_id": previous.id if previous else None,
                },
            )
            self.session.commit()
        except BusinessError:
            self.session.rollback()
            raise
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("同一天只能有一个PUBLISHED派车方案") from exc
        refreshed = self.repository.get(plan.id)
        if refreshed is None:
            raise NotFoundError("派车方案不存在")
        return self._to_detail(refreshed)

    def cancel(
        self,
        plan_id: int,
        actor: User,
        *,
        commit: bool = True,
        audit_context: dict[str, object] | None = None,
    ) -> DispatchPlanDetailResponse:
        plan = self.repository.get_for_update(plan_id)
        if plan is None:
            raise NotFoundError("派车方案不存在")
        if plan.status == DispatchPlanStatus.CANCELLED:
            return self._to_detail(plan)
        if plan.status == DispatchPlanStatus.DRAFT:
            return self._cancel_draft(plan, actor, commit, audit_context)
        elif plan.status == DispatchPlanStatus.PUBLISHED:
            return self._cancel_published(plan, actor, commit, audit_context)
        else:
            raise ConflictError("当前方案状态不能取消")

    def start_delivery(
        self, plan_id: int, order_id: int, actor: User
    ) -> DispatchPlanDetailResponse:
        return self._transition_order_demands(
            plan_id=plan_id,
            order_id=order_id,
            target_status=DeliveryDemandStatus.DELIVERING,
            allowed_current={DeliveryDemandStatus.PUBLISHED},
            action="开始配送",
            actor=actor,
        )

    def complete_delivery(
        self, plan_id: int, order_id: int, actor: User
    ) -> DispatchPlanDetailResponse:
        return self._transition_order_demands(
            plan_id=plan_id,
            order_id=order_id,
            target_status=DeliveryDemandStatus.COMPLETED,
            allowed_current={DeliveryDemandStatus.DELIVERING},
            action="完成配送",
            actor=actor,
        )

    def _transition_order_demands(
        self,
        plan_id: int,
        order_id: int,
        target_status: DeliveryDemandStatus,
        allowed_current: set[DeliveryDemandStatus],
        action: str,
        actor: User,
    ) -> DispatchPlanDetailResponse:
        try:
            from app.services.driver_leave_service import DriverLeaveService
            DriverLeaveService(self.session).lock_resources()
            plan = self.repository.get_for_update(plan_id)
            if plan is None:
                raise NotFoundError("派车方案不存在")
            if plan.status != DispatchPlanStatus.PUBLISHED:
                raise ConflictError(
                    f"只有PUBLISHED方案的任务可以{action}"
                )
            order = self._find_order(plan, order_id, "配送任务")
            from app.domain.enums import UserRole
            if actor.role == UserRole.DRIVER and order.actual_driver_id != actor.id:
                raise NotFoundError("配送任务不存在")
            from app.services.driver_scheduling_service import DriverSchedulingService
            scheduling = DriverSchedulingService(self.session)
            scheduling.repository.lock_vehicle(order.vehicle_id)
            if target_status == DeliveryDemandStatus.DELIVERING:
                driver = scheduling.resolve(plan.delivery_date, order.period.value, order.vehicle_id)
                if driver.id != order.actual_driver_id:
                    raise BusinessError("任务司机与实际排班不一致", 409, "DRIVER_ASSIGNMENT_STALE")
            if target_status == DeliveryDemandStatus.COMPLETED:
                for detail in order.details:
                    if detail.delivery_demand.status not in allowed_current:
                        raise ConflictError(
                            f"需求{detail.delivery_demand_id}当前状态"
                            f"{detail.delivery_demand.status.value}不允许此操作"
                        )
                if any(
                    detail.delivery_status
                    not in {DeliveryStopStatus.SIGNED, DeliveryStopStatus.FAILED}
                    for detail in order.details
                ):
                    raise ConflictError("仍有未完成配送的门店")
            self.demand_status_service.transition_many(
                {detail.delivery_demand_id for detail in order.details},
                target_status,
                allowed_current=allowed_current,
            )
            demand_ids = sorted(
                detail.delivery_demand_id for detail in order.details
            )
            AuditLogService(self.session).add(
                actor,
                (
                    AuditAction.DELIVERY_STARTED
                    if target_status == DeliveryDemandStatus.DELIVERING
                    else AuditAction.DELIVERY_COMPLETED
                ),
                "DispatchOrder",
                order.id,
                {
                    "plan_id": plan.id,
                    "demand_ids": demand_ids,
                    "from_status": next(iter(allowed_current)).value,
                    "to_status": target_status.value,
                },
            )
            self.session.commit()
        except BusinessError:
            self.session.rollback()
            raise
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(f"{action}状态更新失败") from exc

        self.session.expire_all()
        refreshed = self.repository.get(plan_id)
        if refreshed is None:
            raise NotFoundError("派车方案不存在")
        return self._to_detail(refreshed)

    def _cancel_draft(
        self,
        plan: DispatchPlan,
        actor: User,
        commit: bool,
        audit_context: dict[str, object] | None,
    ) -> DispatchPlanDetailResponse:
        assigned_ids = self._assigned_demand_ids(plan)
        other_draft_ids = self.repository.assigned_demand_ids_in_draft_plans(
            plan.delivery_date,
            assigned_ids,
            exclude_plan_id=plan.id,
        )
        demands = self.demand_status_service.get_many(assigned_ids)
        releasable_ids = {
            demand.id
            for demand in demands
            if demand.status == DeliveryDemandStatus.PLANNED
            and demand.id not in other_draft_ids
        }
        return self._change_status(
            plan,
            DispatchPlanStatus.CANCELLED,
            demand_status=DeliveryDemandStatus.PENDING,
            allowed_demand_statuses={DeliveryDemandStatus.PLANNED},
            demand_ids=releasable_ids,
            actor=actor,
            commit=commit,
            audit_context=audit_context,
        )

    def _cancel_published(
        self,
        plan: DispatchPlan,
        actor: User,
        commit: bool,
        audit_context: dict[str, object] | None,
    ) -> DispatchPlanDetailResponse:
        assigned_ids = self._assigned_demand_ids(plan)
        draft_owned_ids = self.repository.assigned_demand_ids_in_draft_plans(
            plan.delivery_date,
            assigned_ids,
            exclude_plan_id=plan.id,
        )
        try:
            self.demand_status_service.transition_many(
                assigned_ids,
                DeliveryDemandStatus.PENDING,
                allowed_current={DeliveryDemandStatus.PUBLISHED},
            )
            self.demand_status_service.transition_many(
                draft_owned_ids,
                DeliveryDemandStatus.PLANNED,
                allowed_current={DeliveryDemandStatus.PENDING},
            )
            self.repository.set_status(plan, DispatchPlanStatus.CANCELLED)
            changes = {
                "before_status": DispatchPlanStatus.PUBLISHED.value,
                "after_status": DispatchPlanStatus.CANCELLED.value,
                "released_demand_ids": sorted(assigned_ids),
            }
            if audit_context:
                changes.update(audit_context)
            AuditLogService(self.session).add(
                actor,
                AuditAction.DISPATCH_PLAN_CANCELLED,
                "DispatchPlan",
                plan.id,
                changes,
            )
            self.session.commit() if commit else self.session.flush()
        except ConflictError:
            if commit:
                self.session.rollback()
            raise
        except IntegrityError as exc:
            if commit:
                self.session.rollback()
            raise ConflictError("派车方案状态更新失败") from exc
        if not commit:
            return self._to_detail(plan)
        refreshed = self.repository.get(plan.id)
        if refreshed is None:
            raise NotFoundError("派车方案不存在")
        return self._to_detail(refreshed)

    def move_demand(
        self,
        plan_id: int,
        data: DispatchDemandMoveRequest,
        actor: User,
        *,
        commit: bool = True,
        audit_context: dict[str, object] | None = None,
    ) -> DispatchPlanDetailResponse:
        try:
            plan = self.repository.get_for_update(plan_id)
            if plan is None:
                raise NotFoundError("派车方案不存在")
            if plan.status != DispatchPlanStatus.DRAFT:
                raise DispatchAdjustmentError(
                    "PLAN_NOT_DRAFT", "只有DRAFT方案可以人工调整"
                )
            if data.source_order_id == data.target_order_id:
                raise DispatchAdjustmentError(
                    "SOURCE_EQUALS_TARGET", "原任务和目标任务不能相同"
                )

            source = self._find_order(plan, data.source_order_id, "原任务")
            target = self._find_order(plan, data.target_order_id, "目标任务")
            detail = next(
                (
                    item
                    for item in source.details
                    if item.delivery_demand_id == data.delivery_demand_id
                ),
                None,
            )
            if detail is None:
                raise DispatchAdjustmentError(
                    "DEMAND_NOT_IN_SOURCE", "配送需求不属于指定原任务"
                )
            if any(
                item.delivery_demand_id == data.delivery_demand_id
                for item in target.details
            ):
                raise DispatchAdjustmentError(
                    "DEMAND_ALREADY_IN_TARGET", "目标任务已包含该配送需求"
                )

            source_load = source.total_load - detail.quantity
            target_load = target.total_load + detail.quantity
            target_result = self.dispatch_validation_service.validate_result(
                DispatchValidationRequest(
                    vehicle_id=target.vehicle_id,
                    delivery_demand_id=detail.delivery_demand_id,
                    route_id=target.route_id,
                    period=target.period,
                    quantity=target_load,
                )
            )
            validation_issues: list[dict[str, object]] = []
            for failure in (
                item
                for item in target_result.constraint_results
                if not item.passed
            ):
                code = {
                    "VEHICLE_NOT_AVAILABLE": "TARGET_VEHICLE_NOT_AVAILABLE",
                    "OVERLOAD": "TARGET_VEHICLE_OVERLOAD",
                    "BELOW_MIN_LOAD": "TARGET_BELOW_MIN_LOAD",
                }.get(failure.code or "", failure.code or "TARGET_INVALID")
                validation_issues.append(
                    {
                        "code": code,
                        "message": failure.reason or "目标任务不满足派车规则",
                        "order_id": target.id,
                        "delivery_demand_id": detail.delivery_demand_id,
                    }
                )

            source_result = self.load_constraint.validate_load(
                source_load,
                source.vehicle.vehicle_type.min_load,
                source.vehicle.vehicle_type.max_load,
            )
            if not source_result.passed:
                code = (
                    "SOURCE_BELOW_MIN_LOAD"
                    if source_result.code == "BELOW_MIN_LOAD"
                    else "SOURCE_VEHICLE_OVERLOAD"
                )
                validation_issues.append(
                    {
                        "code": code,
                        "message": source_result.reason or "原任务不满足载重规则",
                        "order_id": source.id,
                        "delivery_demand_id": detail.delivery_demand_id,
                    }
                )

            if validation_issues:
                raise DispatchAdjustmentValidationError(validation_issues)

            detail.dispatch_order = target
            source.total_load = source_load
            target.total_load = target_load
            self.session.add_all([detail, source, target])
            changes = {
                "plan_id": plan.id,
                "source_order_id": source.id,
                "target_order_id": target.id,
                "quantity": detail.quantity,
                "source_total_load_after": source_load,
                "target_total_load_after": target_load,
            }
            if audit_context:
                changes.update(audit_context)
            AuditLogService(self.session).add(
                actor,
                AuditAction.DISPATCH_DEMAND_MOVED,
                "DeliveryDemand",
                detail.delivery_demand_id,
                changes,
            )
            self.session.commit() if commit else self.session.flush()
        except BusinessError:
            if commit:
                self.session.rollback()
            raise
        except IntegrityError as exc:
            if commit:
                self.session.rollback()
            raise ConflictError("人工调整派车任务失败") from exc

        if not commit:
            return self._to_detail(plan)

        self.session.expire_all()
        refreshed = self.repository.get(plan_id)
        if refreshed is None:
            raise NotFoundError("派车方案不存在")
        return self._to_detail(refreshed)

    def _get_model(self, plan_id: int) -> DispatchPlan:
        plan = self.repository.get(plan_id)
        if plan is None:
            raise NotFoundError("派车方案不存在")
        return plan

    @staticmethod
    def _find_order(
        plan: DispatchPlan, order_id: int, label: str
    ) -> DispatchOrder:
        order = next((item for item in plan.orders if item.id == order_id), None)
        if order is None:
            raise DispatchAdjustmentError(
                "ORDER_NOT_IN_PLAN", f"{label}不属于当前派车方案"
            )
        return order

    def _change_status(
        self,
        plan: DispatchPlan,
        status: DispatchPlanStatus,
        demand_status: DeliveryDemandStatus,
        allowed_demand_statuses: set[DeliveryDemandStatus],
        demand_ids: set[int] | None = None,
        actor: User | None = None,
        commit: bool = True,
        audit_context: dict[str, object] | None = None,
    ) -> DispatchPlanDetailResponse:
        try:
            previous_status = plan.status
            self.demand_status_service.transition_many(
                (
                    demand_ids
                    if demand_ids is not None
                    else self._assigned_demand_ids(plan)
                ),
                demand_status,
                allowed_current=allowed_demand_statuses,
            )
            self.repository.set_status(plan, status)
            if actor is not None:
                changes = {
                    "before_status": previous_status.value,
                    "after_status": status.value,
                    "released_demand_ids": sorted(
                        demand_ids
                        if demand_ids is not None
                        else self._assigned_demand_ids(plan)
                    ),
                }
                if audit_context:
                    changes.update(audit_context)
                AuditLogService(self.session).add(
                    actor,
                    AuditAction.DISPATCH_PLAN_CANCELLED,
                    "DispatchPlan",
                    plan.id,
                    changes,
                )
            self.session.commit() if commit else self.session.flush()
        except ConflictError:
            if commit:
                self.session.rollback()
            raise
        except IntegrityError as exc:
            if commit:
                self.session.rollback()
            raise ConflictError("派车方案状态更新失败") from exc
        if not commit:
            return self._to_detail(plan)
        refreshed = self.repository.get(plan.id)
        if refreshed is None:
            raise NotFoundError("派车方案不存在")
        return self._to_detail(refreshed)

    @staticmethod
    def _assigned_demand_ids(plan: DispatchPlan) -> set[int]:
        return {
            detail.delivery_demand_id
            for order in plan.orders
            for detail in order.details
        }

    @staticmethod
    def _to_summary(plan: DispatchPlan) -> DispatchPlanSummaryResponse:
        return DispatchPlanSummaryResponse(
            id=plan.id,
            delivery_date=plan.delivery_date,
            version=plan.version,
            status=plan.status,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )

    def _to_detail(self, plan: DispatchPlan) -> DispatchPlanDetailResponse:
        return DispatchPlanDetailResponse(
            **self._to_summary(plan).model_dump(),
            orders=[
                PersistedDispatchOrderResponse(
                    actual_driver_id=order.actual_driver_id,
                    driver_username=order.driver_username_snapshot,
                    driver_name=order.driver_name_snapshot,
                    id=order.id,
                    vehicle=DispatchVehicleResponse(
                        id=order.vehicle.id,
                        code=order.vehicle.code,
                        plate_number=order.vehicle.plate_number,
                        vehicle_type_id=order.vehicle.vehicle_type_id,
                        vehicle_type_code=order.vehicle.vehicle_type.code,
                        vehicle_type_name=order.vehicle.vehicle_type.name,
                    ),
                    period=order.period,
                    trip_no=order.trip_no,
                    route=PersistedDispatchRouteResponse(
                        id=order.route.id,
                        code=order.route.code,
                        name=order.route.name,
                    ),
                    total_load=order.total_load,
                    details=[
                        PersistedDispatchOrderDetailResponse(
                            id=detail.id,
                            delivery_demand_id=detail.delivery_demand_id,
                            store_id=detail.delivery_demand.store_id,
                            store_code=detail.delivery_demand.store.code,
                            store_name=detail.delivery_demand.store.name,
                            store_address=detail.delivery_demand.store.address,
                            store_longitude=detail.delivery_demand.store.longitude,
                            store_latitude=detail.delivery_demand.store.latitude,
                            quantity=detail.quantity,
                            status=detail.delivery_demand.status,
                            cargo_category_code=detail.delivery_demand.cargo_category.code,
                            cargo_category_name=detail.delivery_demand.cargo_category.name,
                            priority=detail.delivery_demand.priority,
                            requires_temperature_control=detail.delivery_demand.requires_temperature_control,
                            min_temperature=detail.delivery_demand.min_temperature,
                            max_temperature=detail.delivery_demand.max_temperature,
                            delivery_status=detail.delivery_status,
                            receiver_name=detail.receiver_name,
                            receiver_phone=detail.receiver_phone,
                            signed_at=detail.signed_at,
                            driver_remark=detail.driver_remark,
                            proofs=[DeliveryProofResponse.model_validate(proof, from_attributes=True) for proof in sorted(detail.proofs, key=lambda item: item.id)],
                        )
                        for detail in sorted(order.details, key=lambda item: item.id)
                    ],
                )
                for order in sorted(plan.orders, key=lambda item: item.id)
            ],
            unassigned_demands=[
                PersistedUnassignedDemandResponse(
                    id=item.id,
                    delivery_demand_id=item.delivery_demand_id,
                    store_id=item.delivery_demand.store_id,
                    store_code=item.delivery_demand.store.code,
                    store_name=item.delivery_demand.store.name,
                    store_address=item.delivery_demand.store.address,
                    store_longitude=item.delivery_demand.store.longitude,
                    store_latitude=item.delivery_demand.store.latitude,
                    period=item.delivery_demand.period,
                    quantity=item.delivery_demand.quantity,
                    reasons=item.reasons,
                    cargo_category_code=item.delivery_demand.cargo_category.code,
                    cargo_category_name=item.delivery_demand.cargo_category.name,
                    priority=item.delivery_demand.priority,
                    requires_temperature_control=item.delivery_demand.requires_temperature_control,
                    min_temperature=item.delivery_demand.min_temperature,
                    max_temperature=item.delivery_demand.max_temperature,
                )
                for item in sorted(
                    plan.unassigned_demands, key=lambda record: record.id
                )
            ],
        )
