from datetime import date

from sqlalchemy.orm import Session

from app.domain.enums import DeliveryDemandStatus, DeliveryPriority, DriverTaskStatus
from app.domain.exceptions import BusinessError, ConflictError, NotFoundError
from app.models.dispatch_plan import DispatchOrder
from app.models.user import User
from app.repositories.driver_task_repository import DriverTaskRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.driver import (
    DeliveryProofResponse,
    DeliveryStopFailRequest,
    DeliveryStopSignRequest,
    DriverProfileResponse,
    DriverRouteResponse,
    DriverTaskDetailResponse,
    DriverTaskPageResponse,
    DriverTaskStopResponse,
    DriverTaskSummaryResponse,
    DriverVehicleResponse,
)
from app.services.delivery_stop_service import DeliveryStopService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.driver_scheduling_service import DriverSchedulingService


class DriverService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = DriverTaskRepository(session)
        self.vehicle_repository = VehicleRepository(session)
        self.stop_service = DeliveryStopService(session)

    def profile(self, current_user: User) -> DriverProfileResponse:
        vehicle = self.vehicle_repository.get_by_driver_user_id(current_user.id)
        return DriverProfileResponse(
            user_id=current_user.id,
            username=current_user.username,
            display_name=current_user.display_name,
            vehicle=self._vehicle_response(vehicle) if vehicle else None,
            today_schedules=self._today_schedules(current_user.id),
        )

    def _today_schedules(self, driver_id):
        scheduling = DriverSchedulingService(self.session)
        rows = scheduling.repository.schedules(date.today(), driver_id)
        result = []
        for row in rows:
            vehicle = self.vehicle_repository.get(row.vehicle_id)
            try:
                scheduling.resolve(row.date, row.period, row.vehicle_id, for_update=False)
                conflict = None
            except BusinessError as exc:
                conflict = exc.message
            result.append({"id": row.id, "period": row.period, "kind": row.kind, "status": row.status, "vehicle": self._vehicle_response(vehicle).model_dump(), "conflict": conflict})
        return result

    def today(self, current_user: User) -> list[DriverTaskSummaryResponse]:
        orders, _ = self.repository.list_for_driver(
            current_user.id, delivery_date=date.today()
        )
        return [self._summary(order) for order in orders]

    def history(
        self,
        current_user: User,
        *,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> DriverTaskPageResponse:
        if date_from and date_to and date_from > date_to:
            raise ConflictError("开始日期不能晚于结束日期")
        orders, total = self.repository.list_for_driver(
            current_user.id,
            date_from=date_from,
            date_to=date_to,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return DriverTaskPageResponse(
            items=[self._summary(order) for order in orders],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_task(self, task_id: int, current_user: User) -> DriverTaskDetailResponse:
        order = self.repository.get_for_driver(task_id, current_user.id)
        if order is None:
            # A not-found response avoids revealing another driver's task IDs.
            raise NotFoundError("配送任务不存在")
        return self._detail(order)

    def start(self, task_id: int, current_user: User) -> DriverTaskDetailResponse:
        order = self._owned_order(task_id, current_user.id)
        DispatchPlanService(self.session).start_delivery(
            order.plan_id, order.id, current_user
        )
        return self.get_task(task_id, current_user)

    def complete(self, task_id: int, current_user: User) -> DriverTaskDetailResponse:
        order = self._owned_order(task_id, current_user.id)
        DispatchPlanService(self.session).complete_delivery(
            order.plan_id, order.id, current_user
        )
        return self.get_task(task_id, current_user)

    def get_stop(
        self, task_id: int, stop_id: int, current_user: User
    ) -> DriverTaskStopResponse:
        _, stop = self.stop_service.get_owned_stop(task_id, stop_id, current_user.id)
        return self._stop_response(stop, self._stop_sequence(task_id, stop_id, current_user))

    def arrive_stop(
        self, task_id: int, stop_id: int, current_user: User
    ) -> DriverTaskStopResponse:
        self.stop_service.arrive(task_id, stop_id, current_user)
        return self.get_stop(task_id, stop_id, current_user)

    def sign_stop(
        self,
        task_id: int,
        stop_id: int,
        data: DeliveryStopSignRequest,
        current_user: User,
    ) -> DriverTaskStopResponse:
        self.stop_service.sign(task_id, stop_id, data, current_user)
        return self.get_stop(task_id, stop_id, current_user)

    def fail_stop(
        self,
        task_id: int,
        stop_id: int,
        data: DeliveryStopFailRequest,
        current_user: User,
    ) -> DriverTaskStopResponse:
        self.stop_service.fail(task_id, stop_id, data, current_user)
        return self.get_stop(task_id, stop_id, current_user)

    def upload_proof(
        self,
        task_id: int,
        stop_id: int,
        content_type: str,
        content: bytes,
        current_user: User,
    ) -> DeliveryProofResponse:
        proof = self.stop_service.upload_proof(
            task_id, stop_id, content_type, content, current_user
        )
        return DeliveryProofResponse.model_validate(proof, from_attributes=True)

    def _owned_order(self, task_id: int, driver_user_id: int) -> DispatchOrder:
        order = self.repository.get_for_driver(task_id, driver_user_id)
        if order is None:
            raise NotFoundError("配送任务不存在")
        return order

    @classmethod
    def _summary(cls, order: DispatchOrder) -> DriverTaskSummaryResponse:
        return DriverTaskSummaryResponse(
            id=order.id,
            delivery_date=order.plan.delivery_date,
            plan_id=order.plan_id,
            plan_version=order.plan.version,
            period=order.period,
            trip_no=order.trip_no,
            route=DriverRouteResponse(
                id=order.route.id,
                code=order.route.code,
                name=order.route.name,
            ),
            total_load=order.total_load,
            status=cls._task_status(order),
            stop_count=len(order.details),
            highest_priority=cls._highest_priority(order),
        )

    @classmethod
    def _detail(cls, order: DispatchOrder) -> DriverTaskDetailResponse:
        summary = cls._summary(order)
        details = sorted(order.details, key=lambda item: item.id)
        return DriverTaskDetailResponse(
            **summary.model_dump(),
            vehicle=cls._vehicle_response(order.vehicle),
            stops=[cls._stop_response(item, index) for index, item in enumerate(details, start=1)],
        )

    @staticmethod
    def _stop_response(item, sequence: int) -> DriverTaskStopResponse:
        return DriverTaskStopResponse(
            id=item.id,
            sequence=sequence,
            delivery_demand_id=item.delivery_demand_id,
            store_id=item.delivery_demand.store.id,
            store_code=item.delivery_demand.store.code,
            store_name=item.delivery_demand.store.name,
            address=item.delivery_demand.store.address,
            contact_name=item.delivery_demand.store.contact_name,
            contact_phone=item.delivery_demand.store.contact_phone,
            longitude=item.delivery_demand.store.longitude,
            latitude=item.delivery_demand.store.latitude,
            quantity=item.quantity,
            cargo_category_code=item.delivery_demand.cargo_category.code,
            cargo_category_name=item.delivery_demand.cargo_category.name,
            priority=item.delivery_demand.priority,
            requires_temperature_control=item.delivery_demand.requires_temperature_control,
            min_temperature=item.delivery_demand.min_temperature,
            max_temperature=item.delivery_demand.max_temperature,
            delivery_status=item.delivery_status,
            arrived_at=item.arrived_at,
            signed_at=item.signed_at,
            receiver_name=item.receiver_name,
            receiver_phone=item.receiver_phone,
            failure_reason=item.failure_reason,
            driver_remark=item.driver_remark,
            proofs=[
                DeliveryProofResponse.model_validate(proof, from_attributes=True)
                for proof in sorted(item.proofs, key=lambda proof: proof.id)
            ],
        )

    def _stop_sequence(
        self, task_id: int, stop_id: int, current_user: User
    ) -> int:
        order = self.repository.get_for_driver(task_id, current_user.id)
        if order is None:
            raise NotFoundError("配送任务不存在")
        details = sorted(order.details, key=lambda item: item.id)
        return next(
            index
            for index, item in enumerate(details, start=1)
            if item.id == stop_id
        )

    @staticmethod
    def _vehicle_response(vehicle) -> DriverVehicleResponse:
        return DriverVehicleResponse(
            id=vehicle.id,
            code=vehicle.code,
            plate_number=vehicle.plate_number,
            vehicle_type_code=vehicle.vehicle_type.code.value,
            vehicle_type_name=vehicle.vehicle_type.name,
        )

    @staticmethod
    def _task_status(order: DispatchOrder) -> DriverTaskStatus:
        statuses = {
            item.delivery_demand.status for item in order.details
        }
        mapping = {
            DeliveryDemandStatus.PUBLISHED: DriverTaskStatus.PUBLISHED,
            DeliveryDemandStatus.DELIVERING: DriverTaskStatus.DELIVERING,
            DeliveryDemandStatus.COMPLETED: DriverTaskStatus.COMPLETED,
        }
        if len(statuses) == 1:
            status = next(iter(statuses))
            if status in mapping:
                return mapping[status]
        return DriverTaskStatus.MIXED

    @staticmethod
    def _highest_priority(order: DispatchOrder) -> DeliveryPriority:
        ranks = {
            DeliveryPriority.NORMAL: 0,
            DeliveryPriority.HIGH: 1,
            DeliveryPriority.URGENT: 2,
        }
        return max(
            (item.delivery_demand.priority for item in order.details),
            key=lambda priority: ranks[priority],
            default=DeliveryPriority.NORMAL,
        )
