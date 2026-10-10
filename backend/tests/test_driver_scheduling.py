from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.domain.enums import DeliveryDemandStatus
from app.models.audit_log import AuditLog
from app.models.vehicle import Vehicle
from app.models.driver_scheduling import DriverSchedule
from tests.test_driver_api import _setup_driver_tasks, _driver_headers

ROOT = '/api/v1/driver-management'


def context(client, session):
    a, b, order_a, order_b, demand_a, demand_b = _setup_driver_tasks(session)
    schedule = session.scalar(select(DriverSchedule).where(DriverSchedule.vehicle_id == order_a.vehicle_id))
    # Candidate is standby, not silently borrowed from an available default vehicle.
    session.get(Vehicle, order_b.vehicle_id).driver_user_id = None
    session.commit()
    assert client.put(ROOT + '/attendances', json={'driver_id': b.id, 'date': date.today().isoformat(), 'period': 'MORNING', 'available': True}).status_code == 200
    return a, b, order_a, demand_a, schedule


def substitute(client, schedule, driver_id):
    return client.post(f'{ROOT}/schedules/{schedule.id}/substitute', json={'driver_id': driver_id})


def test_leave_then_substitution_retains_default_and_changes_ownership(client, session):
    a, b, order, demand, schedule = context(client, session)
    response = client.post(ROOT + '/leaves', json={'driver_id': a.id, 'start_date': date.today().isoformat(), 'end_date': date.today().isoformat(), 'period': 'MORNING', 'reason': '请假'})
    assert response.status_code == 200
    assert client.post(f"{ROOT}/leave-requests/{response.json()['id']}/review", json={'decision': 'APPROVED'}).status_code == 200
    assert substitute(client, schedule, b.id).status_code == 200
    assert session.get(Vehicle, order.vehicle_id).driver_user_id == a.id
    assert order.actual_driver_id == b.id
    ah, bh = _driver_headers(client, a.username), _driver_headers(client, b.username)
    assert client.get(f'/api/driver/tasks/{order.id}', headers=ah).status_code == 404
    assert client.post(f'/api/driver/tasks/{order.id}/start', headers=ah).status_code == 404
    assert client.get(f'/api/driver/tasks/{order.id}', headers=bh).status_code == 200
    assert client.post(f'/api/driver/tasks/{order.id}/start', headers=bh).status_code == 200
    stop_id = client.get(f'/api/driver/tasks/{order.id}', headers=bh).json()['stops'][0]['id']
    assert client.post(f'/api/driver/tasks/{order.id}/stops/{stop_id}/arrive', headers=bh).status_code == 200
    assert client.post(f'/api/driver/tasks/{order.id}/stops/{stop_id}/sign', headers=bh, json={'receiver_name': '真实测试签收人'}).status_code == 200
    assert client.post(f'/api/driver/tasks/{order.id}/complete', headers=bh).status_code == 200
    history = client.get('/api/driver/tasks/history', headers=bh).json()
    assert any(t['id'] == order.id for t in history['items'])


@pytest.mark.parametrize('status', [DeliveryDemandStatus.DELIVERING, DeliveryDemandStatus.COMPLETED])
def test_execution_locks_substitution_and_rolls_back(client, session, status):
    a, b, order, demand, schedule = context(client, session)
    demand.status = status
    session.commit()
    response = substitute(client, schedule, b.id)
    assert response.status_code == 409
    assert response.json()['code'] == 'TASK_DRIVER_LOCKED'
    session.refresh(schedule); session.refresh(order)
    assert schedule.driver_id == a.id
    assert order.actual_driver_id == a.id
    assert session.scalar(select(AuditLog).where(AuditLog.action == 'DRIVER_SUBSTITUTION_CONFIRMED')) is None


def test_substitution_repeat_is_idempotent(client, session):
    a, b, order, demand, schedule = context(client, session)
    assert substitute(client, schedule, b.id).status_code == 200
    assert substitute(client, schedule, b.id).status_code == 200
    logs = list(session.scalars(select(AuditLog).where(AuditLog.action == 'DRIVER_SUBSTITUTION_CONFIRMED')))
    assert len(logs) == 1


@pytest.mark.parametrize('condition', ['inactive', 'leave', 'absent', 'conflict'])
def test_unavailable_candidate_is_rejected(client, session, condition):
    a, b, order, demand, schedule = context(client, session)
    if condition == 'inactive':
        b.is_active = False; session.commit()
    elif condition == 'leave':
        client.post(ROOT + '/leaves', json={'driver_id': b.id, 'start_date': date.today().isoformat(), 'end_date': date.today().isoformat(), 'period': 'ALL_DAY', 'reason': '请假'})
    elif condition == 'absent':
        client.put(ROOT + '/attendances', json={'driver_id': b.id, 'date': date.today().isoformat(), 'period': 'MORNING', 'available': False})
    else:
        other = session.scalar(select(DriverSchedule).where(DriverSchedule.driver_id == b.id))
        other.period = 'MORNING'; session.commit()
    candidates = client.get(f'{ROOT}/schedules/{schedule.id}/candidates').json()
    assert next(c for c in candidates if c['id'] == b.id)['reason']
    assert substitute(client, schedule, b.id).status_code == 409


def test_default_vehicle_change_does_not_rewrite_completed_history(client, session):
    a, b, order, demand, schedule = context(client, session)
    demand.status = DeliveryDemandStatus.COMPLETED
    session.commit()
    assert client.put(f'{ROOT}/drivers/{a.id}/default-vehicle', json={'vehicle_id': None}).status_code == 200
    ah = _driver_headers(client, a.username)
    history = client.get('/api/driver/tasks/history', headers=ah).json()
    assert any(t['id'] == order.id for t in history['items'])
    assert order.actual_driver_id == a.id


def test_driver_cannot_manage_shifts(client, session):
    a, b, order, demand, schedule = context(client, session)
    headers = _driver_headers(client, a.username)
    assert client.get(ROOT + '/schedules', headers=headers).status_code == 403
    assert client.post(f'{ROOT}/schedules/{schedule.id}/substitute', headers=headers, json={'driver_id': b.id}).status_code == 403


def test_leave_end_next_day_normal_schedule_can_restore_default(client, session):
    a, b, order, demand, schedule = context(client, session)
    tomorrow = date.today() + timedelta(days=1)
    from app.models.vehicle_attendance import VehicleAttendance
    session.add(VehicleAttendance(date=tomorrow, vehicle_id=order.vehicle_id, available=True)); session.commit()
    client.post(ROOT + '/leaves', json={'driver_id': a.id, 'start_date': date.today().isoformat(), 'end_date': date.today().isoformat(), 'period': 'ALL_DAY', 'reason': '一天假'})
    client.put(ROOT + '/attendances', json={'driver_id': a.id, 'date': tomorrow.isoformat(), 'period': 'MORNING', 'available': True})
    assigned = client.post(ROOT + '/schedules', json={'vehicle_id': order.vehicle_id, 'date': tomorrow.isoformat(), 'period': 'MORNING'})
    assert assigned.status_code == 200
    assert assigned.json()['driver_id'] == a.id


def test_missing_driver_gives_explicit_unassigned_reason(client):
    from tests.test_auto_dispatch_api import create_terrain_route_and_stores, create_vehicle
    terrain, _, stores = create_terrain_route_and_stores(client, [100])
    vehicle = create_vehicle(client, terrain['id'], 'SMALL_VAN', '小包', 1, 300, 'TEST-NODRIVER')
    driver = client.get(ROOT + '/drivers', params={'day': '2026-09-24'}).json()[0]
    client.put(ROOT + '/attendances', json={'driver_id': driver['id'], 'date': '2026-09-24', 'period': 'MORNING', 'available': False})
    result = client.post('/api/v1/auto-dispatch', json={'date': '2026-09-24'}).json()
    assert result['trips'] == []
    assert '司机' in result['unassigned_demands'][0]['reasons'][0]


def test_viewer_read_only_dispatcher_shift_but_not_password(client, session):
    from app.domain.enums import UserRole
    from app.services.auth_service import AuthService
    a, b, order, demand, schedule = context(client, session)
    for name, role in [('viewer-shifts', UserRole.VIEWER), ('dispatcher-shifts', UserRole.DISPATCHER)]:
        AuthService(session).create_user(name, 'TestPass123!', role)
        result = client.post('/api/v1/auth/login', json={'username': name, 'password': 'TestPass123!'}).json()
        headers = {'Authorization': 'Bearer ' + result['access_token']}
        assert client.get(ROOT + '/schedules', headers=headers).status_code == 200
        assert client.post(f'{ROOT}/drivers/{a.id}/password', headers=headers, json={'password': 'NewTest123!'}).status_code == 403
        changed = client.put(ROOT + '/attendances', headers=headers, json={'driver_id': b.id, 'date': date.today().isoformat(), 'period': 'MORNING', 'available': True})
        assert changed.status_code == (403 if role == UserRole.VIEWER else 200)


def test_demo_account_initialization_reuses_credentials_without_silent_reset(client, session):
    from app.scripts.seed_driver_accounts import initialize, render_local
    from app.models.user import User
    from app.core.security import verify_password
    a, b, order, demand, schedule = context(client, session)
    vehicle = session.get(Vehicle, order.vehicle_id)
    vehicle.code = 'DEMO_ACCOUNT_TEST'
    session.commit()
    actor = session.scalar(select(User).where(User.username == 'test-admin'))
    before = a.password_hash
    rows = initialize(session, actor, {a.username: 'DriverPass123!'})
    row = next(r for r in rows if r[0].id == a.id)
    assert row[2] == 'DriverPass123!'
    assert a.password_hash == before
    assert 'DriverPass123!' in render_local(rows)
    unknown = initialize(session, actor, {})
    assert next(r for r in unknown if r[0].id == a.id)[2] is None
    assert a.password_hash == before
    reset = initialize(session, actor, {}, reset=True)
    password = next(r for r in reset if r[0].id == a.id)[2]
    assert password != 'DriverPass123!'
    assert verify_password(password, a.password_hash)


def test_default_vehicle_binding_collision_is_rejected(client, session):
    a, b, order, demand, schedule = context(client, session)
    result = client.put(f'{ROOT}/drivers/{b.id}/default-vehicle', json={'vehicle_id': order.vehicle_id})
    assert result.status_code == 409
    assert result.json()['code'] == 'DEFAULT_BINDING_CONFLICT'
    assert session.get(Vehicle, order.vehicle_id).driver_user_id == a.id


def test_driver_read_endpoints_do_not_acquire_write_locks(client, session):
    from sqlalchemy import event
    a, b, order, demand, schedule = context(client, session)
    headers = _driver_headers(client, a.username)
    statements = []

    def capture(state):
        if getattr(state.statement, '_for_update_arg', None) is not None:
            statements.append(state.statement)

    event.listen(session, 'do_orm_execute', capture)
    try:
        for path in [ROOT + '/drivers', ROOT + '/workbench']:
            assert client.get(path, params={'day': date.today().isoformat()}).status_code == 200
        assert client.get(f'{ROOT}/schedules/{schedule.id}/candidates').status_code == 200
        assert client.get('/api/driver/profile', headers=headers).status_code == 200
        assert statements == []
    finally:
        event.remove(session, 'do_orm_execute', capture)


def test_substitution_still_acquires_write_locks(client, session):
    from sqlalchemy import event
    a, b, order, demand, schedule = context(client, session)
    statements = []

    def capture(state):
        if getattr(state.statement, '_for_update_arg', None) is not None:
            statements.append(state.statement)

    event.listen(session, 'do_orm_execute', capture)
    try:
        assert substitute(client, schedule, b.id).status_code == 200
        assert statements
    finally:
        event.remove(session, 'do_orm_execute', capture)
