from datetime import date

from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.domain.enums import DeliveryDemandStatus, UserRole
from app.domain.exceptions import BusinessError, NotFoundError
from app.models.driver_scheduling import DriverAttendance, DriverAttendanceRule, DriverLeave, DriverSchedule
from app.models.user import User
from app.repositories.driver_scheduling_repository import DriverSchedulingRepository
from app.services.audit_log_service import AuditLogService


class DriverSchedulingService:
    def __init__(self, session):
        self.session = session
        self.repository = DriverSchedulingRepository(session)

    def driver(self, driver_id, *, for_update=True):
        driver = self.repository.lock_driver(driver_id, for_update=for_update)
        if not driver or driver.role != UserRole.DRIVER:
            raise NotFoundError("司机不存在")
        return driver

    def list_schedules(self, day=None, driver_id=None):
        return self.repository.schedules(day, driver_id)

    def workbench(self, day):
        vehicles = self.repository.vehicles()
        rows = []
        for vehicle in vehicles:
            for period in ("MORNING", "AFTERNOON"):
                schedule = self.repository.for_vehicle(day, period, vehicle.id)
                try:
                    self.resolve(day, period, vehicle.id, for_update=False)
                    conflict = None
                except BusinessError as exc:
                    conflict = exc.message
                effective = self.resolve_effective_driver(vehicle.id, day, period)
                driver = self.driver(effective['effective_driver_id'], for_update=False) if effective['effective_driver_id'] else self.driver(schedule.driver_id, for_update=False) if schedule else None
                rows.append({"schedule_id": schedule.id if schedule else None, "vehicle_id": vehicle.id, "plate_number": vehicle.plate_number, "period": period, "default_driver_id": vehicle.driver_user_id, "driver_id": driver.id if driver else None, "driver_name": (driver.display_name or driver.username) if driver else None, "kind": schedule.kind if schedule else None, "conflict": conflict})
        return rows

    def list_leaves(self):
        return self.repository.leaves()

    def eligibility(self, day, period, driver_id, vehicle_id, *, for_update=True):
        driver = self.driver(driver_id, for_update=for_update)
        if not driver.is_active:
            return "司机账号已停用"
        if self.repository.on_leave(day, period, driver_id):
            return "司机在该班次请假"
        attendance = self.attendance_info(day, period, driver_id)
        if not attendance['available']:
            return "司机未登记该班次出勤"
        conflict = self.repository.for_driver(day, period, driver_id)
        if conflict and conflict.vehicle_id != vehicle_id:
            return "司机已安排其他车辆"
        return None

    def resolve(self, day, period, vehicle_id, *, for_update=True):
        # 展示可用性不申请写锁；业务动作仍默认加锁并重新校验。
        vehicle = self.repository.lock_vehicle(vehicle_id, for_update=for_update)
        if not vehicle or not vehicle.is_active:
            raise BusinessError("车辆已停用或不存在", 409, "VEHICLE_INACTIVE")
        if not vehicle.vehicle_type.is_active:
            raise BusinessError("车型已停用", 409, "VEHICLE_TYPE_INACTIVE")
        attendance = self.repository.vehicle_attendance(day, vehicle_id)
        if not attendance or not attendance.available:
            raise BusinessError("车辆当天不可出勤", 409, "VEHICLE_UNAVAILABLE")
        schedule = self.repository.for_vehicle(day, period, vehicle_id)
        from app.repositories.driver_leave_repository import DriverLeaveRepository
        confirmed = DriverLeaveRepository(self.session).confirmed(day, period, vehicle_id)
        if confirmed and (confirmed.original_driver_id != vehicle.driver_user_id or not schedule or schedule.status != "ACTIVE" or schedule.driver_id != confirmed.substitute_driver_id):
            raise BusinessError("确认记录与当前绑定/排班不一致，请重新核查", 409, "DRIVER_ASSIGNMENT_STALE")
        primary_leave = self.repository.leave_for_shift(day, period, vehicle.driver_user_id) if vehicle.driver_user_id else None
        if primary_leave and primary_leave.status == "PENDING":
            raise BusinessError("常驻司机请假待审批，暂缓新分配和发布", 409, "DRIVER_LEAVE_PENDING_REVIEW")
        if primary_leave and not confirmed:
            raise BusinessError("司机已请假，尚无已确认代班", 409, "DRIVER_ON_LEAVE_NO_CONFIRMED_SUBSTITUTE")
        if schedule and schedule.kind == "SUBSTITUTE" and (not confirmed or confirmed.substitute_driver_id != schedule.driver_id):
            raise BusinessError("代班尚未经管理员确认", 409, "DRIVER_ASSIGNMENT_CONFLICT")
        driver_id = schedule.driver_id if schedule and schedule.status == "ACTIVE" else vehicle.driver_user_id
        if not driver_id:
            raise BusinessError("司机未安排，请先登记司机出勤和实际排班", 409, "DRIVER_UNASSIGNED")
        reason = self.eligibility(day, period, driver_id, vehicle_id, for_update=for_update)
        if reason:
            leave = self.repository.leave_for_shift(day, period, driver_id)
            code = "SUBSTITUTE_DRIVER_UNAVAILABLE" if confirmed else "DRIVER_LEAVE_PENDING_REVIEW" if leave and leave.status == "PENDING" else "DRIVER_ASSIGNED_TO_OTHER_VEHICLE" if self.repository.for_driver(day, period, driver_id) else "DRIVER_UNAVAILABLE"
            raise BusinessError(reason, 409, code)
        from app.repositories.driver_leave_repository import DriverLeaveRepository
        if any(o.vehicle_id != vehicle_id for o in DriverLeaveRepository(self.session).driver_orders(driver_id, day, day, period)):
            raise BusinessError("司机已分配其他车辆的已发布任务", 409, "DRIVER_ASSIGNED_TO_OTHER_VEHICLE")
        return self.driver(driver_id, for_update=for_update)

    def resolve_effective_driver(self, vehicle_id, delivery_date, period):
        try:
            driver = self.resolve(delivery_date, period, vehicle_id, for_update=False)
            schedule = self.repository.for_vehicle(delivery_date, period, vehicle_id)
            return {"effective_driver_id": driver.id, "assignment_type": "SUBSTITUTE" if schedule and schedule.kind == "SUBSTITUTE" else "PRIMARY", "availability_status": "AVAILABLE", "unavailable_reason": None, "code": None}
        except BusinessError as exc:
            return {"effective_driver_id": None, "assignment_type": "UNAVAILABLE", "availability_status": "UNAVAILABLE", "unavailable_reason": exc.message, "code": exc.code}

    def commit(self, actor, action, row, changes):
        try:
            self.session.flush()
            AuditLogService(self.session).add(actor, action, type(row).__name__, row.id, changes)
            self.session.commit()
            return row
        except IntegrityError as exc:
            self.session.rollback()
            raise BusinessError("司机或车辆班次冲突，请刷新后重试", 409, "DRIVER_SCHEDULE_CONFLICT") from exc

    def set_attendance(self, data, actor):
        self.driver(data.driver_id)
        row = self.repository.attendance(data.date, data.period, data.driver_id)
        if row is None:
            row = DriverAttendance(**data.model_dump(), actor_id=actor.id)
            self.session.add(row)
        else:
            row.available = data.available
            row.actor_id = actor.id
        row.override_enabled = True
        return self.commit(actor, "DRIVER_ATTENDANCE_UPDATED", row, data.model_dump())

    def attendance_info(self, day, period, driver_id):
        override = self.repository.attendance(day, period, driver_id)
        fixed = self.repository.fixed_attendance(day, period, driver_id)
        use_override = override is not None and override.override_enabled
        return {
            'available': bool(override.available if use_override else fixed and fixed.available),
            'source': 'ONCE' if use_override else 'FIXED' if fixed else 'UNSET',
            'fixed_available': fixed.available if fixed else None,
            'effective_date': fixed.effective_date if fixed else None,
        }

    def set_fixed_attendance(self, driver_id, data, actor):
        self.driver(driver_id)
        row = self.repository.fixed_attendance(data.effective_date, data.period, driver_id)
        if row is None or row.effective_date != data.effective_date:
            row = DriverAttendanceRule(driver_id=driver_id, **data.model_dump(), actor_id=actor.id)
            self.session.add(row)
        else:
            row.available = data.available
            row.actor_id = actor.id
        # 永久修改替代生效当天的临时设置，但不删除记录或覆盖其他日期调整。
        override = self.repository.attendance(data.effective_date, data.period, driver_id)
        before_override = None
        if override and override.override_enabled:
            before_override = override.available
            override.override_enabled = False
        return self.commit(actor, 'DRIVER_FIXED_ATTENDANCE_UPDATED', row, {
            **data.model_dump(), 'replaced_day_override': before_override,
        })

    def assign(self, data, actor):
        try:
            from app.services.driver_leave_service import DriverLeaveService
            DriverLeaveService(self.session).lock_resources()
            vehicle = self.repository.lock_vehicle(data.vehicle_id)
            if not vehicle or not vehicle.is_active:
                raise BusinessError("车辆已停用或不存在", 409, "VEHICLE_INACTIVE")
            driver_id = data.driver_id or vehicle.driver_user_id
            if driver_id is None:
                raise BusinessError("车辆没有默认司机，请选择实际司机", 409, "DRIVER_UNASSIGNED")
            if vehicle.driver_user_id and driver_id != vehicle.driver_user_id:
                raise BusinessError("不能通过普通排班绕过代班确认，请使用管理员代班流程", 409, "USE_SUBSTITUTE")
            reason = DriverLeaveService(self.session).candidate_reason(data.date, data.period, driver_id, vehicle.id)
            if reason:
                raise BusinessError(reason, 409, "DRIVER_UNAVAILABLE")
            attendance = self.repository.vehicle_attendance(data.date, vehicle.id)
            if not attendance or not attendance.available:
                raise BusinessError("车辆当天不可出勤", 409, "VEHICLE_UNAVAILABLE")
            existing = self.repository.for_vehicle(data.date, data.period, vehicle.id)
            if existing:
                if existing.driver_id == driver_id:
                    return existing
                raise BusinessError("班次已有司机，请使用明确代班操作", 409, "USE_SUBSTITUTE")
            row = DriverSchedule(date=data.date, period=data.period, vehicle_id=vehicle.id, driver_id=driver_id, kind="NORMAL", status="ACTIVE", actor_id=actor.id)
            self.session.add(row)
            self.sync_orders(row)
            return self.commit(actor, "DRIVER_SCHEDULE_CREATED", row, data.model_dump())
        except BusinessError:
            self.session.rollback()
            raise
        except IntegrityError as exc:
            self.session.rollback()
            raise BusinessError("司机或车辆班次冲突，请刷新重试", 409, "DRIVER_SCHEDULE_CONFLICT") from exc

    def sync_orders(self, schedule):
        orders = self.repository.orders(schedule.date, schedule.period, schedule.vehicle_id)
        for order in orders:
            statuses = {item.delivery_demand.status for item in order.details}
            if statuses & {DeliveryDemandStatus.DELIVERING, DeliveryDemandStatus.COMPLETED}:
                raise BusinessError("配送中或已完成任务禁止普通代班，请处理任务交接", 409, "TASK_DRIVER_LOCKED")
        driver = self.driver(schedule.driver_id)
        for order in orders:
            order.actual_driver_id = driver.id
            order.driver_username_snapshot = driver.username
            order.driver_name_snapshot = driver.display_name

    def substitute(self, schedule_id, driver_id, actor):
        from app.services.driver_leave_service import DriverLeaveService
        workflow = DriverLeaveService(self.session)
        workflow.admin(actor)
        # Compatibility endpoint remains ADMIN-only and uses the same confirmed workflow.
        existing = self.repository.schedule(schedule_id, for_update=False)
        if existing is None:
            raise NotFoundError("排班不存在")
        if existing.driver_id == driver_id:
            return existing
        if any(d.delivery_demand.status in {DeliveryDemandStatus.DELIVERING, DeliveryDemandStatus.COMPLETED} for o in self.repository.orders(existing.date, existing.period, existing.vehicle_id, for_update=False) for d in o.details):
            raise BusinessError("配送中或已完成任务禁止普通代班", 409, "TASK_DRIVER_LOCKED")
        from app.schemas.driver_leave import SubstitutionInput
        leave = self.repository.leave_for_shift(existing.date, existing.period, existing.original_driver_id or existing.driver_id)
        data = SubstitutionInput(leave_request_id=leave.id if leave else None, vehicle_id=existing.vehicle_id, substitute_driver_id=driver_id, date=existing.date, period=existing.period)
        proposed = workflow.propose(data, actor, commit=False)
        workflow.confirm(proposed.id, actor)
        return self.repository.schedule(schedule_id, for_update=False)

    def candidates(self, schedule_id):
        row = self.repository.schedule(schedule_id, for_update=False)
        if row is None:
            raise NotFoundError("排班不存在")
        locked = any(item.delivery_demand.status in {DeliveryDemandStatus.DELIVERING, DeliveryDemandStatus.COMPLETED} for order in self.repository.orders(row.date, row.period, row.vehicle_id, for_update=False) for item in order.details)
        return [{"id": d.id, "username": d.username, "display_name": d.display_name, "reason": "存在配送中或已完成任务，不能普通代班" if locked else self.eligibility(row.date, row.period, d.id, row.vehicle_id, for_update=False)} for d in self.repository.drivers()]

    def create_leave(self, data, actor):
        from app.services.driver_leave_service import DriverLeaveService
        from app.schemas.driver_leave import LeaveRequestInput
        return DriverLeaveService(self.session).submit(LeaveRequestInput(**data.model_dump(exclude={"driver_id", "remark"})), actor, data.driver_id)

    def cancel_leave(self, leave_id, actor):
        from app.services.driver_leave_service import DriverLeaveService
        return DriverLeaveService(self.session).withdraw(leave_id, actor)

    def bind_default(self, driver_id, vehicle_id, actor):
        try:
            from app.services.driver_leave_service import DriverLeaveService
            DriverLeaveService(self.session).lock_resources()
            driver = self.driver(driver_id)
            old = self.repository.default_vehicle(driver_id)
            target = self.repository.lock_vehicle(vehicle_id) if vehicle_id else None
            if vehicle_id and (not target or not target.is_active or not driver.is_active):
                raise BusinessError("司机或车辆未启用", 409, "DEFAULT_BINDING_INVALID")
            if target and target.driver_user_id not in (None, driver_id):
                raise BusinessError("车辆已有默认司机，请先解除绑定", 409, "DEFAULT_BINDING_CONFLICT")
            before = old.id if old else None
            if old and old != target:
                old.driver_user_id = None
                self.session.flush()
            if target:
                target.driver_user_id = driver_id
            self.commit(actor, "DRIVER_DEFAULT_VEHICLE_CHANGED", driver, {"before_vehicle_id": before, "after_vehicle_id": vehicle_id})
            return {"driver_id": driver_id, "vehicle_id": vehicle_id}
        except BusinessError:
            self.session.rollback()
            raise

    def list_drivers(self, day):
        from app.repositories.driver_task_repository import DriverTaskRepository
        result = []
        for driver in self.repository.drivers():
            vehicle = self.repository.default_vehicle(driver.id, for_update=False)
            schedules = self.repository.schedules(day, driver.id)
            attendance_details = {p: self.attendance_info(day, p, driver.id) for p in ("MORNING", "AFTERNOON")}
            attendances = {p: info['available'] for p, info in attendance_details.items()}
            _, count = DriverTaskRepository(self.session).list_for_driver(driver.id, delivery_date=day, limit=1)
            result.append({"id": driver.id, "username": driver.username, "display_name": driver.display_name, "is_active": driver.is_active, "default_vehicle_id": vehicle.id if vehicle else None, "default_plate": vehicle.plate_number if vehicle else None, "today_task_count": count, "attendance": attendances, "attendance_details": attendance_details, "schedules": [{"id": s.id, "period": s.period, "vehicle_id": s.vehicle_id, "kind": s.kind} for s in schedules]})
        return result

    def create_driver(self, data, actor):
        user = User(username=data.username.strip(), display_name=data.display_name, password_hash=hash_password(data.password), role=UserRole.DRIVER, is_active=True)
        self.session.add(user)
        return self.commit(actor, "USER_CREATED", user, {"role": "DRIVER"})

    def update_driver(self, driver_id, data, actor):
        user = self.driver(driver_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("is_active") is None and "is_active" in changes:
            raise BusinessError("启用状态不能为null")
        for key, value in changes.items():
            setattr(user, key, value)
        if "is_active" in changes:
            user.token_version += 1
        return self.commit(actor, "USER_UPDATED", user, changes)

    def reset_password(self, driver_id, password, actor):
        user = self.driver(driver_id)
        user.password_hash = hash_password(password)
        user.token_version += 1
        self.commit(actor, "PASSWORD_CHANGED", user, {"password_reset": True})
