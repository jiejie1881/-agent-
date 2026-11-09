"""Idempotent local-only driver credentials. Never prints passwords."""

if __name__ == "__main__":
    raise SystemExit("RETIRED_TEST_FIXTURE_ONLY: archived demonstration CLI is disabled")

import argparse
from datetime import date
from pathlib import Path
import secrets

from sqlalchemy import select

from app.core.security import verify_password
from app.domain.enums import UserRole
from app.infrastructure.database.session import SessionLocal
from app.models.user import User
from app.models.vehicle import Vehicle
from app.repositories.user_repository import UserRepository
from app.schemas.driver_scheduling import DriverCreateInput, AttendanceInput, ScheduleInput
from app.services.driver_scheduling_service import DriverSchedulingService


def ensure_demo_driver(session, vehicle, actor):
    """Reuse existing binding; only new demo accounts receive random passwords."""
    service = DriverSchedulingService(session)
    if vehicle.driver_user_id:
        return service.driver(vehicle.driver_user_id), None
    username = f"driver{vehicle.id:03}"
    user = UserRepository(session).get_by_username(username)
    password = None
    if user is None:
        password = secrets.token_urlsafe(18)
        user = service.create_driver(DriverCreateInput(username=username, display_name=f"演示司机{vehicle.id:03}", password=password), actor)
    if user.role != UserRole.DRIVER:
        raise RuntimeError("演示账号名称被非司机占用，请手动处理")
    current = service.repository.default_vehicle(user.id)
    if current and current.id != vehicle.id:
        raise RuntimeError("演示账号已有其他默认车辆，停止自动换绑")
    service.bind_default(user.id, vehicle.id, actor)
    return user, password


def read_local_passwords(paths):
    values = {}
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.startswith('|'):
                continue
            cells = [item.strip() for item in line.strip('|').split('|')]
            if len(cells) >= 2 and cells[0] not in ('账号', '登录用户名', '---'):
                values[cells[0]] = cells[1]
    return values


def initialize(session, actor, passwords, reset=False):
    service = DriverSchedulingService(session)
    vehicles = list(session.scalars(select(Vehicle).where(Vehicle.code.like('DEMO_%'), Vehicle.is_active.is_(True)).order_by(Vehicle.id)))
    records = []
    for vehicle in vehicles:
        user, generated = ensure_demo_driver(session, vehicle, actor)
        password = generated or passwords.get(user.username)
        if password and not verify_password(password, user.password_hash):
            password = None
        if password is None and reset:
            password = secrets.token_urlsafe(18)
            service.reset_password(user.id, password, actor)
        records.append((user, vehicle, password))
    existing_ids = {user.id for user, _, _ in records}
    for user in service.repository.drivers():
        if user.id in existing_ids:
            continue
        vehicle = service.repository.default_vehicle(user.id)
        password = passwords.get(user.username)
        if password and not verify_password(password, user.password_hash):
            password = None
        records.append((user, vehicle, password))
    return records


def render_local(records):
    lines = ['# 司机测试账号（仅本地 Demo）', '', '禁止提交或公开分享。数据库仅保存密码哈希。账号密码仅适用于本地演示环境。', '',
             '登录：微信小程序司机登录页。已停用账号无法登录；没有今日任务时需登记司机/车辆出勤、排班并发布方案。', '',
             '| 登录用户名 | 演示初始密码 | 司机姓名 | 默认车辆 | 账号状态 |', '| --- | --- | --- | --- | --- |']
    for user, vehicle, password in records:
        lines.append(f"| {user.username} | {password or '未知：需显式重置'} | {user.display_name or '未填写'} | {vehicle.plate_number if vehicle else '未绑定'} | {'启用' if user.is_active else '停用'} |")
    lines.extend(['', '## 代班演示', '登记司机 A 请假 → 司机 B 班次出勤 → 排班工作台选择 B 代班 → 发布/未开始任务转归 B → B 登录查看。默认车辆绑定不变；配送中和已完成任务不能普通代班。', '',
                  '重复初始化不重置现有密码。文件丢失或密码未知时，必须显式使用 --reset-existing-demo-credentials；会使相关司机旧 Token 失效。不得反查密码哈希。'])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-demo', action='store_true', required=True, help='明确仅用于本地Demo数据库')
    parser.add_argument('--output', default='../docs/local/司机测试账号_本地.md')
    parser.add_argument('--previous-credentials', default='../local-credentials/司机账号密码.md')
    parser.add_argument('--reset-existing-demo-credentials', action='store_true')
    parser.add_argument('--schedule-date', action='append', default=[], help='可重复指定，仅为已登记车辆出勤的Demo车创建正常排班')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    passwords = read_local_passwords([Path(args.previous_credentials), output])
    with SessionLocal() as session:
        actor = session.scalar(select(User).where(User.username == 'demo_admin', User.role == UserRole.ADMIN, User.is_active.is_(True)))
        if not actor:
            raise SystemExit('缺少启用的demo_admin；停止初始化')
        records = initialize(session, actor, passwords, args.reset_existing_demo_credentials)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_local(records), encoding='utf-8')
        service = DriverSchedulingService(session)
        for day_text in args.schedule_date:
            day = date.fromisoformat(day_text)
            for driver, vehicle, _ in records:
                if vehicle is None:
                    continue
                attendance = service.repository.vehicle_attendance(day, vehicle.id)
                if not driver.is_active or not attendance:
                    continue
                for period in ('MORNING', 'AFTERNOON'):
                    existing = service.repository.for_vehicle(day, period, vehicle.id)
                    if existing:
                        continue  # 不覆盖已安排的代班或实际司机。
                    service.set_attendance(AttendanceInput(date=day, period=period, driver_id=driver.id, available=attendance.available), actor)
                    if attendance.available and not service.repository.on_leave(day, period, driver.id):
                        service.assign(ScheduleInput(date=day, period=period, driver_id=driver.id, vehicle_id=vehicle.id), actor)
        print('Local account file generated; drivers:', len(records), 'unknown passwords:', sum(p is None for _, _, p in records))


if __name__ == '__main__':
    main()
