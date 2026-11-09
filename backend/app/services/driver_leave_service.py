from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from app.domain.enums import DeliveryDemandStatus, UserRole
from app.domain.exceptions import BusinessError, NotFoundError, PermissionDeniedError
from app.models.driver_scheduling import DriverLeave, DriverSchedule, DriverSubstitution
from app.repositories.driver_leave_repository import DriverLeaveRepository
from app.services.driver_scheduling_service import DriverSchedulingService


class DriverLeaveService:
    def __init__(self, session):
        self.session = session
        self.repository = DriverLeaveRepository(session)
        self.scheduling = DriverSchedulingService(session)

    def admin(self, actor):
        if actor.role != UserRole.ADMIN:
            raise PermissionDeniedError("只有管理员可以审批或确认代班")

    def lock_resources(self):
        # Consistent ordering serializes resource decisions, including empty shift slots.
        # Read-only endpoints never call this; optimize granularity later if volume warrants it.
        for v in self.scheduling.repository.vehicles():
            self.scheduling.repository.lock_vehicle(v.id)
        for d in self.scheduling.repository.drivers():
            self.scheduling.driver(d.id)

    def row(self, leave_id, actor=None, *, lock=False):
        row = self.scheduling.repository.leave(leave_id, for_update=lock)
        if row is None or (actor and actor.role == UserRole.DRIVER and row.driver_id != actor.id):
            raise NotFoundError("请假申请不存在")
        return row

    def serialize(self, row, actor):
        driver = self.scheduling.driver(row.driver_id, for_update=False)
        vehicle = self.scheduling.repository.default_vehicle(row.driver_id, for_update=False)
        sensitive = actor.role == UserRole.ADMIN or actor.id == row.driver_id
        return {"id": row.id, "driver_id": row.driver_id, "driver_name": driver.display_name or driver.username,
                "vehicle_id": vehicle.id if vehicle else None, "plate_number": vehicle.plate_number if vehicle else None,
                "start_date": row.start_date, "end_date": row.end_date, "period": row.period,
                "leave_type": row.leave_type if sensitive else None, "reason": row.reason if sensitive else None,
                "status": row.status, "reviewed_by": row.reviewed_by, "reviewed_at": row.reviewed_at,
                "review_remark": row.review_remark if sensitive else None, "created_at": row.created_at, "updated_at": row.updated_at}

    def submit(self, data, actor, driver_id=None):
        if actor.role != UserRole.DRIVER:
            self.admin(actor)
        target = actor.id if actor.role == UserRole.DRIVER else driver_id
        try:
            self.lock_resources()
            self.scheduling.driver(target)
            for existing in self.repository.leaves(target):
                if existing.status in {"PENDING", "APPROVED"} and existing.start_date <= data.end_date and existing.end_date >= data.start_date and (existing.period == "ALL_DAY" or data.period == "ALL_DAY" or existing.period == data.period):
                    raise BusinessError("存在时间重叠的有效请假申请", 409, "LEAVE_OVERLAP")
            row = DriverLeave(driver_id=target, **data.model_dump(), actor_id=actor.id, status="PENDING")
            self.session.add(row)
            return self.scheduling.commit(actor, "DRIVER_LEAVE_REQUESTED", row, {"status": "PENDING"})
        except BusinessError:
            self.session.rollback()
            raise

    def withdraw(self, leave_id, actor):
        try:
            self.lock_resources()
            row = self.row(leave_id, actor, lock=True)
            if actor.role != UserRole.DRIVER:
                self.admin(actor)
            if row.status != "PENDING":
                raise BusinessError("只能撤回待审批申请", 409, "LEAVE_STATE_INVALID")
            row.status = "CANCELLED"
            return self.scheduling.commit(actor, "DRIVER_LEAVE_WITHDRAWN", row, {"before": "PENDING", "after": row.status})
        except BusinessError:
            self.session.rollback()
            raise

    def affected(self, row):
        orders = self.repository.driver_orders(row.driver_id, row.start_date, row.end_date, row.period)
        return [{"task_id": o.id, "plan_id": o.plan_id, "vehicle_id": o.vehicle_id, "date": o.plan.delivery_date,
                 "period": o.period, "statuses": sorted({d.delivery_demand.status.value for d in o.details}),
                 "driver_locked": any(d.delivery_demand.status in {DeliveryDemandStatus.DELIVERING, DeliveryDemandStatus.COMPLETED} for d in o.details)} for o in orders]

    def review(self, leave_id, data, actor):
        self.admin(actor)
        try:
            self.lock_resources()
            row = self.row(leave_id, lock=True)
            if row.status != "PENDING":
                raise BusinessError("申请已经处理，请刷新", 409, "LEAVE_STATE_INVALID")
            row.status = data.decision
            row.reviewed_by, row.reviewed_at, row.review_remark = actor.id, datetime.now(timezone.utc), data.review_remark
            # Do not rewrite published/executing task ownership; conflicts remain queryable.
            return self.scheduling.commit(actor, "DRIVER_LEAVE_REVIEWED", row, {"before": "PENDING", "after": row.status, "affected_task_ids": [x['task_id'] for x in self.affected(row)]})
        except BusinessError:
            self.session.rollback()
            raise

    def candidate_reason(self, day, period, driver_id, vehicle_id):
        reason = self.scheduling.eligibility(day, period, driver_id, vehicle_id, for_update=False)
        if reason:
            return reason
        orders = self.repository.driver_orders(driver_id, day, day, period)
        if any(o.vehicle_id != vehicle_id for o in orders):
            return "存在其他车辆的已发布任务"
        default = self.scheduling.repository.default_vehicle(driver_id, for_update=False)
        if default and default.id != vehicle_id:
            attendance = self.scheduling.repository.vehicle_attendance(day, default.id)
            shift = self.scheduling.repository.for_vehicle(day, period, default.id)
            if attendance and attendance.available and default.is_active and (not shift or shift.driver_id == driver_id):
                return "代班会使常驻车辆失去司机，请先安排替补或调整该车出勤"
        return None

    def validate_target(self, data):
        vehicle = self.scheduling.repository.lock_vehicle(data.vehicle_id, for_update=False)
        if not vehicle or not vehicle.driver_user_id:
            raise BusinessError("目标车辆没有常驻司机", 409, "DRIVER_UNASSIGNED")
        if data.leave_request_id:
            leave = self.row(data.leave_request_id)
            if leave.status != "APPROVED" or leave.driver_id != vehicle.driver_user_id or not (leave.start_date <= data.date <= leave.end_date) or leave.period not in ("ALL_DAY", data.period):
                raise BusinessError("代班必须关联该司机已批准且覆盖目标班次的请假", 409, "LEAVE_NOT_APPROVED")
        return vehicle

    def propose(self, data, actor, *, commit=True):
        self.admin(actor)
        try:
            self.lock_resources()
            vehicle = self.validate_target(data)
            reason = self.candidate_reason(data.date, data.period, data.substitute_driver_id, vehicle.id)
            if reason or data.substitute_driver_id == vehicle.driver_user_id:
                raise BusinessError(reason or "不能由请假司机本人代班", 409, "SUBSTITUTE_DRIVER_UNAVAILABLE")
            row = DriverSubstitution(**data.model_dump(), original_driver_id=vehicle.driver_user_id, status="PENDING")
            self.session.add(row)
            if not commit:
                self.session.flush()
                return row
            return self.scheduling.commit(actor, "DRIVER_SUBSTITUTION_PROPOSED", row, {"status": "PENDING"})
        except BusinessError:
            self.session.rollback()
            raise

    def confirm(self, row_id, actor):
        self.admin(actor)
        try:
            self.lock_resources()
            row = self.repository.substitution(row_id, lock=True)
            if not row:
                raise NotFoundError("代班记录不存在")
            if row.status == "CONFIRMED":
                self.scheduling.resolve(row.date, row.period, row.vehicle_id)
                return row
            if row.status != "PENDING":
                raise BusinessError("已取消的代班不能确认", 409, "SUBSTITUTION_STATE_INVALID")
            vehicle = self.validate_target(row)
            if vehicle.driver_user_id != row.original_driver_id:
                raise BusinessError("长期绑定发生变化，请重新提交", 409, "DRIVER_ASSIGNMENT_STALE")
            reason = self.candidate_reason(row.date, row.period, row.substitute_driver_id, vehicle.id)
            if reason:
                raise BusinessError(reason, 409, "SUBSTITUTE_DRIVER_UNAVAILABLE")
            if self.repository.confirmed(row.date, row.period, vehicle.id):
                raise BusinessError("该班次已有有效代班", 409, "DRIVER_ASSIGNMENT_CONFLICT")
            schedule = self.scheduling.repository.for_vehicle(row.date, row.period, vehicle.id)
            if not schedule:
                schedule = DriverSchedule(date=row.date, period=row.period, vehicle_id=vehicle.id, actor_id=actor.id)
                self.session.add(schedule)
            schedule.driver_id, schedule.original_driver_id, schedule.kind, schedule.status = row.substitute_driver_id, row.original_driver_id, "SUBSTITUTE", "ACTIVE"
            row.status, row.active_driver_id, row.active_vehicle_id = "CONFIRMED", row.substitute_driver_id, vehicle.id
            row.confirmed_by, row.confirmed_at = actor.id, datetime.now(timezone.utc)
            self.session.flush()
            self.scheduling.resolve(row.date, row.period, vehicle.id)
            self.scheduling.sync_orders(schedule)
            return self.scheduling.commit(actor, "DRIVER_SUBSTITUTION_CONFIRMED", row, {"before": "PENDING", "after": "CONFIRMED", "actual_driver_id": row.substitute_driver_id})
        except (BusinessError, IntegrityError) as exc:
            self.session.rollback()
            if isinstance(exc, IntegrityError):
                raise BusinessError("司机或车辆班次冲突", 409, "DRIVER_ASSIGNMENT_CONFLICT") from exc
            raise

    def cancel_substitution(self, row_id, actor):
        self.admin(actor)
        try:
            self.lock_resources()
            row = self.repository.substitution(row_id, lock=True)
            if not row:
                raise NotFoundError("代班记录不存在")
            if row.status == "CANCELLED":
                return row
            if row.status == "CONFIRMED":
                schedule = self.scheduling.repository.for_vehicle(row.date, row.period, row.vehicle_id)
                if not schedule or schedule.driver_id != row.substitute_driver_id:
                    raise BusinessError("排班已经变化，请人工核查", 409, "DRIVER_ASSIGNMENT_STALE")
                schedule.driver_id, schedule.kind = row.original_driver_id, "NORMAL"
                self.scheduling.sync_orders(schedule)
            row.status, row.active_driver_id, row.active_vehicle_id = "CANCELLED", None, None
            return self.scheduling.commit(actor, "DRIVER_SUBSTITUTION_CANCELLED", row, {"after": "CANCELLED", "requires_revalidation": True})
        except (BusinessError, IntegrityError) as exc:
            self.session.rollback()
            if isinstance(exc, IntegrityError):
                raise BusinessError("原司机已有其他车辆班次，无法恢复", 409, "DRIVER_ASSIGNMENT_CONFLICT") from exc
            raise
