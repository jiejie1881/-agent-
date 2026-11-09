from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.driver_scheduling import DriverAttendance
from app.services.driver_scheduling_service import DriverSchedulingService
from tests.test_driver_scheduling import ROOT, context


def fixed(client, driver_id, day, available=True, period='MORNING'):
    return client.put(f'{ROOT}/drivers/{driver_id}/fixed-attendance', json={
        'effective_date': day.isoformat(), 'period': period, 'available': available,
    })


def info(client, driver_id, day, period='MORNING'):
    rows = client.get(ROOT + '/drivers', params={'day': day.isoformat()}).json()
    return next(row for row in rows if row['id'] == driver_id)['attendance_details'][period]


def test_fixed_attendance_applies_daily_from_effective_date(client, session):
    a, b, order, demand, schedule = context(client, session)
    day = date.today()
    assert fixed(client, a.id, day).status_code == 200
    assert info(client, a.id, day)['source'] == 'FIXED'
    assert info(client, a.id, day + timedelta(days=3))['available'] is True
    assert info(client, a.id, day - timedelta(days=1))['source'] == 'UNSET'
    assert info(client, a.id, day + timedelta(days=3), 'AFTERNOON')['source'] == 'UNSET'


def test_once_override_does_not_change_fixed_attendance(client, session):
    a, b, order, demand, schedule = context(client, session)
    day = date.today()
    fixed(client, a.id, day)
    result = client.put(ROOT + '/attendances', json={'driver_id': a.id, 'date': day.isoformat(), 'period': 'MORNING', 'available': False})
    assert result.status_code == 200
    today = info(client, a.id, day)
    assert today['source'] == 'ONCE' and today['available'] is False
    assert today['fixed_available'] is True
    assert info(client, a.id, day + timedelta(days=1))['available'] is True


def test_permanent_replaces_selected_day_override_but_retains_other_dates(client, session):
    a, b, order, demand, schedule = context(client, session)
    day = date.today()
    tomorrow = day + timedelta(days=1)
    client.put(ROOT + '/attendances', json={'driver_id': a.id, 'date': tomorrow.isoformat(), 'period': 'MORNING', 'available': True})
    assert fixed(client, a.id, day, False).status_code == 200
    assert info(client, a.id, day)['source'] == 'FIXED'
    assert info(client, a.id, day)['available'] is False
    retained = session.scalar(select(DriverAttendance).where(DriverAttendance.driver_id == a.id, DriverAttendance.date == day, DriverAttendance.period == 'MORNING'))
    assert retained is not None and retained.override_enabled is False
    assert info(client, a.id, tomorrow)['source'] == 'ONCE'
    assert info(client, a.id, tomorrow + timedelta(days=1))['available'] is False


def test_later_fixed_change_keeps_previous_dates(client, session):
    a, b, order, demand, schedule = context(client, session)
    day = date.today()
    fixed(client, a.id, day, True)
    fixed(client, a.id, day + timedelta(days=2), False)
    assert info(client, a.id, day)['available'] is True
    assert info(client, a.id, day + timedelta(days=2))['available'] is False


def test_fixed_attendance_does_not_bypass_leave_or_conflict(client, session):
    a, b, order, demand, schedule = context(client, session)
    day = date.today()
    fixed(client, a.id, day)
    client.post(ROOT + '/leaves', json={'driver_id': a.id, 'start_date': day.isoformat(), 'end_date': day.isoformat(), 'period': 'MORNING', 'reason': '固定班次也不能绕过请假'})
    service = DriverSchedulingService(session)
    assert service.eligibility(day, 'MORNING', a.id, order.vehicle_id) == '司机在该班次请假'
    fixed(client, b.id, day, True, 'AFTERNOON')
    assert service.eligibility(day, 'AFTERNOON', b.id, order.vehicle_id) == '司机已安排其他车辆'


def test_future_schedule_uses_fixed_attendance_without_daily_registration(client, session):
    from app.models.vehicle_attendance import VehicleAttendance
    a, b, order, demand, schedule = context(client, session)
    tomorrow = date.today() + timedelta(days=1)
    fixed(client, a.id, date.today())
    session.add(VehicleAttendance(date=tomorrow, vehicle_id=order.vehicle_id, available=True))
    session.commit()
    assert session.scalar(select(DriverAttendance).where(DriverAttendance.driver_id == a.id, DriverAttendance.date == tomorrow)) is None
    response = client.post(ROOT + '/schedules', json={'date': tomorrow.isoformat(), 'period': 'MORNING', 'vehicle_id': order.vehicle_id, 'driver_id': a.id})
    assert response.status_code == 200
    assert DriverSchedulingService(session).resolve(tomorrow, 'MORNING', order.vehicle_id).id == a.id


@pytest.mark.parametrize('role,expected', [('ADMIN', 200), ('DISPATCHER', 200), ('VIEWER', 403), ('DRIVER', 403)])
def test_fixed_attendance_rbac(client, session, role, expected):
    from app.domain.enums import UserRole
    from app.services.auth_service import AuthService
    a, b, order, demand, schedule = context(client, session)
    user = AuthService(session).create_user('fixed-' + role, 'TestFixed123!', UserRole(role))
    token = client.post('/api/v1/auth/login', json={'username': user.username, 'password': 'TestFixed123!'}).json()['access_token']
    response = client.put(f'{ROOT}/drivers/{a.id}/fixed-attendance', headers={'Authorization': 'Bearer ' + token}, json={'effective_date': date.today().isoformat(), 'period': 'MORNING', 'available': True})
    assert response.status_code == expected


def test_fixed_update_audit_and_invalid_period(client, session):
    a, b, order, demand, schedule = context(client, session)
    from app.models.audit_log import AuditLog
    result = client.put(f'{ROOT}/drivers/{a.id}/fixed-attendance', json={'effective_date': date.today().isoformat(), 'period': 'NIGHT', 'available': True})
    assert result.status_code == 422
    assert session.scalar(select(AuditLog).where(AuditLog.action == 'DRIVER_FIXED_ATTENDANCE_UPDATED')) is None
    fixed(client, a.id, date.today())
    assert session.scalar(select(AuditLog).where(AuditLog.action == 'DRIVER_FIXED_ATTENDANCE_UPDATED')) is not None
