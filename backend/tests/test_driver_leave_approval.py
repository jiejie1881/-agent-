from datetime import date, timedelta
import pytest
from sqlalchemy import select
from app.domain.enums import DeliveryDemandStatus, UserRole
from app.models.driver_scheduling import DriverLeave, DriverSubstitution, DriverSchedule
from app.models.audit_log import AuditLog
from app.models.vehicle import Vehicle
from app.services.auth_service import AuthService
from tests.test_driver_scheduling import context, ROOT
from tests.test_driver_api import _driver_headers


def payload(**changes):
    return {'start_date': str(date.today()), 'end_date': str(date.today()), 'period': 'MORNING', 'leave_type': '事假', 'reason': '个人事项', **changes}


def submit(client, driver, **changes):
    return client.post('/api/driver/leaves', headers=_driver_headers(client, driver.username), json=payload(**changes))


def approved(client, driver):
    row = submit(client, driver).json()
    assert client.post(f"{ROOT}/leave-requests/{row['id']}/review", json={'decision': 'APPROVED', 'review_remark': '同意'}).status_code == 200
    return row


def propose(client, leave, vehicle_id, driver_id, **changes):
    return client.post(ROOT + '/substitutions', json={'leave_request_id': leave['id'], 'vehicle_id': vehicle_id, 'substitute_driver_id': driver_id, 'date': str(date.today()), 'period': 'MORNING', **changes})


def effective(client, vehicle_id):
    return next(x for x in client.get(ROOT + '/effective-drivers', params={'day': str(date.today()), 'period': 'MORNING'}).json() if x['vehicle_id'] == vehicle_id)


def test_driver_submit_own_and_private_history(client, session):
    a, b, order, demand, schedule = context(client, session)
    response = submit(client, a)
    assert response.status_code == 200
    assert response.json()['status'] == 'PENDING'
    assert response.json()['driver_id'] == a.id
    assert client.get('/api/driver/leaves', headers=_driver_headers(client, b.username)).json() == []


def test_client_driver_id_injection_forbidden(client, session):
    a, b, *_ = context(client, session)
    assert submit(client, a, driver_id=b.id).status_code == 422


@pytest.mark.parametrize('invalid', [{'end_date': '2000-01-01'}, {'reason': '  '}, {'period': 'NIGHT'}])
def test_invalid_leave_input(client, session, invalid):
    a, *_ = context(client, session)
    assert submit(client, a, **invalid).status_code == 422


def test_overlap_and_distinct_shifts(client, session):
    a, *_ = context(client, session)
    assert submit(client, a).status_code == 200
    assert submit(client, a).json()['code'] == 'LEAVE_OVERLAP'
    assert submit(client, a, period='ALL_DAY').status_code == 409
    assert submit(client, a, period='AFTERNOON').status_code == 200


def test_pending_withdraw_only_own(client, session):
    a, b, *_ = context(client, session)
    leave = submit(client, a).json()
    url = f"/api/driver/leaves/{leave['id']}/withdraw"
    assert client.post(url, headers=_driver_headers(client, b.username)).status_code == 404
    assert client.post(url, headers=_driver_headers(client, a.username)).json()['status'] == 'CANCELLED'
    assert client.post(url, headers=_driver_headers(client, a.username)).status_code == 409


@pytest.mark.parametrize('decision', ['APPROVED', 'REJECTED'])
def test_admin_review_once_with_audit(client, session, decision):
    a, *_ = context(client, session)
    leave = submit(client, a).json()
    url = f"{ROOT}/leave-requests/{leave['id']}/review"
    assert client.post(url, json={'decision': decision}).json()['status'] == decision
    assert client.post(url, json={'decision': decision}).status_code == 409
    assert len(list(session.scalars(select(AuditLog).where(AuditLog.action == 'DRIVER_LEAVE_REVIEWED')))) == 1


def test_approved_cannot_be_withdrawn_by_driver(client, session):
    a, *_ = context(client, session)
    leave = approved(client, a)
    assert client.post(f"/api/driver/leaves/{leave['id']}/withdraw", headers=_driver_headers(client, a.username)).status_code == 409


@pytest.mark.parametrize('role', [UserRole.DISPATCHER, UserRole.VIEWER])
def test_read_privacy_no_approval_or_confirmation(client, session, role):
    a, *_ = context(client, session)
    leave = submit(client, a).json()
    AuthService(session).create_user('read-role', 'TestPass123!', role)
    token = client.post('/api/v1/auth/login', json={'username': 'read-role', 'password': 'TestPass123!'}).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    for path in ['/leaves', '/leave-requests']:
        assert client.get(ROOT + path, headers=headers).json()[0]['reason'] is None
    assert client.post(f"{ROOT}/leave-requests/{leave['id']}/review", headers=headers, json={'decision': 'APPROVED'}).status_code == 403
    assert client.post(ROOT + '/substitutions/1/confirm', headers=headers).status_code == 403


@pytest.mark.parametrize('reviewed,code', [(False, 'DRIVER_LEAVE_PENDING_REVIEW'), (True, 'DRIVER_ON_LEAVE_NO_CONFIRMED_SUBSTITUTE')])
def test_leave_excludes_vehicle(client, session, reviewed, code):
    a, b, order, *_ = context(client, session)
    approved(client, a) if reviewed else submit(client, a)
    result = effective(client, order.vehicle_id)
    assert result['code'] == code
    assert result['effective_driver_id'] is None


def test_recommendation_read_only_and_pending_not_effective(client, session):
    a, b, order, demand, schedule = context(client, session)
    leave = approved(client, a)
    results = client.get(ROOT + '/substitution-candidates', params={'day': str(date.today()), 'period': 'MORNING', 'vehicle_id': order.vehicle_id}).json()
    assert b.id in [x['driver_id'] for x in results['candidates']]
    assert schedule.driver_id == a.id and session.scalar(select(DriverSubstitution)) is None
    proposed = propose(client, leave, order.vehicle_id, b.id)
    assert proposed.status_code == 200
    assert proposed.json()['status'] == 'PENDING'
    assert effective(client, order.vehicle_id)['effective_driver_id'] is None


def test_confirm_changes_actual_not_default_and_repeat_safe(client, session):
    a, b, order, demand, schedule = context(client, session)
    leave = approved(client, a)
    row = propose(client, leave, order.vehicle_id, b.id).json()
    url = f"{ROOT}/substitutions/{row['id']}/confirm"
    assert client.post(url).status_code == 200
    assert client.post(url).status_code == 200
    assert effective(client, order.vehicle_id)['effective_driver_id'] == b.id
    assert session.get(Vehicle, order.vehicle_id).driver_user_id == a.id
    assert order.actual_driver_id == b.id
    listed = client.get(ROOT + '/substitutions').json()[0]
    assert listed['substitute_driver_name'] == (b.display_name or b.username)
    assert 'password_hash' not in listed
    assert client.get(f'/api/driver/tasks/{order.id}', headers=_driver_headers(client, a.username)).status_code == 404
    assert client.get(f'/api/driver/tasks/{order.id}', headers=_driver_headers(client, b.username)).status_code == 200
    assert len(list(session.scalars(select(AuditLog).where(AuditLog.action == 'DRIVER_SUBSTITUTION_CONFIRMED')))) == 1


def test_confirm_rechecks_leave_changed_after_proposal(client, session):
    a, b, order, *_ = context(client, session)
    row = propose(client, approved(client, a), order.vehicle_id, b.id).json()
    assert submit(client, b).status_code == 200
    result = client.post(f"{ROOT}/substitutions/{row['id']}/confirm")
    assert result.status_code == 409
    assert session.get(DriverSubstitution, row['id']).status == 'PENDING'
    assert session.scalar(select(AuditLog).where(AuditLog.action == 'DRIVER_SUBSTITUTION_CONFIRMED')) is None


@pytest.mark.parametrize('status', [DeliveryDemandStatus.DELIVERING, DeliveryDemandStatus.COMPLETED])
def test_executed_tasks_not_reassigned(client, session, status):
    a, b, order, demand, schedule = context(client, session)
    leave = approved(client, a)
    assert client.get(f"{ROOT}/leave-requests/{leave['id']}").json()['affected_tasks']
    row = propose(client, leave, order.vehicle_id, b.id).json()
    demand.status = status; session.commit()
    result = client.post(f"{ROOT}/substitutions/{row['id']}/confirm")
    assert result.json()['code'] == 'TASK_DRIVER_LOCKED'
    session.refresh(schedule)
    assert schedule.driver_id == a.id and order.actual_driver_id == a.id


def test_cancel_confirmed_restores_but_vehicle_unavailable(client, session):
    a, b, order, *_ = context(client, session)
    row = propose(client, approved(client, a), order.vehicle_id, b.id).json()
    assert client.post(f"{ROOT}/substitutions/{row['id']}/confirm").status_code == 200
    assert client.post(f"{ROOT}/substitutions/{row['id']}/cancel").status_code == 200
    assert effective(client, order.vehicle_id)['code'] == 'DRIVER_ON_LEAVE_NO_CONFIRMED_SUBSTITUTE'
    assert client.post(f"{ROOT}/substitutions/{row['id']}/confirm").status_code == 409


def test_substitute_later_disabled_blocks_new_use(client, session):
    a, b, order, *_ = context(client, session)
    row = propose(client, approved(client, a), order.vehicle_id, b.id).json()
    client.post(f"{ROOT}/substitutions/{row['id']}/confirm")
    b.is_active = False; session.commit()
    assert effective(client, order.vehicle_id)['code'] == 'SUBSTITUTE_DRIVER_UNAVAILABLE'


def test_same_vehicle_double_confirmation_rejected(client, session):
    a, b, order, *_ = context(client, session)
    leave = approved(client, a)
    first = propose(client, leave, order.vehicle_id, b.id).json()
    second = propose(client, leave, order.vehicle_id, b.id).json()
    assert client.post(f"{ROOT}/substitutions/{first['id']}/confirm").status_code == 200
    assert client.post(f"{ROOT}/substitutions/{second['id']}/confirm").status_code == 409


def test_next_day_default_and_existing_cargo_tests_unmodified(client, session):
    from app.models.vehicle_attendance import VehicleAttendance
    from app.services.driver_scheduling_service import DriverSchedulingService
    from app.schemas.driver_scheduling import FixedAttendanceInput
    a, b, order, *_ = context(client, session)
    row = propose(client, approved(client, a), order.vehicle_id, b.id).json()
    client.post(f"{ROOT}/substitutions/{row['id']}/confirm")
    tomorrow = date.today() + timedelta(days=1)
    session.add(VehicleAttendance(date=tomorrow, vehicle_id=order.vehicle_id, available=True)); session.commit()
    actor = AuthService(session).repository.get_by_username('test-admin')
    DriverSchedulingService(session).set_fixed_attendance(a.id, FixedAttendanceInput(effective_date=tomorrow, period='MORNING', available=True), actor)
    result = DriverSchedulingService(session).resolve_effective_driver(order.vehicle_id, tomorrow, 'MORNING')
    assert result['effective_driver_id'] == a.id and result['assignment_type'] == 'PRIMARY'


def test_auto_dispatch_and_publish_use_only_confirmed_substitute(client, session):
    from tests.test_auto_dispatch_api import create_terrain_route_and_stores, create_vehicle
    from app.models.user import User
    terrain, route, stores = create_terrain_route_and_stores(client, [100])
    vehicle = create_vehicle(client, terrain['id'], 'SMALL_VAN', '小包', 1, 300, 'LEAVE-AUTO')
    driver = session.scalar(select(User).where(User.username == f"test-driver-{vehicle['id']}"))
    assert client.put(f'{ROOT}/drivers/{driver.id}/default-vehicle', json={'vehicle_id': vehicle['id']}).status_code == 200
    standby = AuthService(session).create_user('auto-standby', 'TestPass123!', UserRole.DRIVER)
    assert client.put(ROOT + '/attendances', json={'driver_id': standby.id, 'date': '2026-09-24', 'period': 'MORNING', 'available': True}).status_code == 200
    first = client.post('/api/v1/auto-dispatch', json={'date': '2026-09-24'}).json()
    assert first['trips']
    response = client.post(ROOT + '/leaves', json={'driver_id': driver.id, 'start_date': '2026-09-24', 'end_date': '2026-09-24', 'period': 'MORNING', 'reason': '测试申请'})
    assert response.status_code == 200
    leave = response.json()
    pending = client.post('/api/v1/auto-dispatch', json={'date': '2026-09-24'}).json()
    assert not pending['trips']
    assert any('DRIVER_LEAVE_PENDING_REVIEW' in reason for item in pending['unassigned_demands'] for reason in item['reasons'])
    assert client.post(f"{ROOT}/leave-requests/{leave['id']}/review", json={'decision': 'APPROVED'}).status_code == 200
    proposal = propose(client, leave, vehicle['id'], standby.id, date='2026-09-24').json()
    assert not client.post('/api/v1/auto-dispatch', json={'date': '2026-09-24'}).json()['trips']
    assert client.post(f"{ROOT}/substitutions/{proposal['id']}/confirm").status_code == 200
    result = client.post('/api/v1/auto-dispatch', json={'date': '2026-09-24'}).json()
    assert result['trips'] and result['unassigned_demands'] == []
    plan = client.get(f"/api/v1/dispatch-plans/{result['plan_id']}").json()
    assert plan['orders'][0]['actual_driver_id'] == standby.id
    # A later change invalidates a computed draft at publication, without partial publication.
    standby.is_active = False; session.commit()
    published = client.post(f"/api/v1/dispatch-plans/{result['plan_id']}/publish")
    assert published.status_code == 409
    assert any(issue['code'] == 'SUBSTITUTE_DRIVER_UNAVAILABLE' for issue in published.json()['issues'])
    assert client.get(f"/api/v1/dispatch-plans/{result['plan_id']}").json()['status'] == 'DRAFT'


def test_default_other_vehicle_not_silently_abandoned(client, session):
    a, b, order, *_ = context(client, session)
    other = session.scalar(select(Vehicle).where(Vehicle.id != order.vehicle_id))
    other.driver_user_id = b.id; session.commit()
    response = propose(client, approved(client, a), order.vehicle_id, b.id)
    assert response.status_code == 409
    assert '常驻车辆' in response.json()['detail']


def test_normal_schedule_cannot_bypass_confirmation(client, session):
    a, b, order, *_ = context(client, session)
    tomorrow = date.today() + timedelta(days=1)
    response = client.post(ROOT + '/schedules', json={'date': str(tomorrow), 'period': 'MORNING', 'vehicle_id': order.vehicle_id, 'driver_id': b.id})
    assert response.json()['code'] == 'USE_SUBSTITUTE'


def test_same_driver_other_vehicle_cannot_confirm(client, session):
    a, b, order, *_ = context(client, session)
    first = propose(client, approved(client, a), order.vehicle_id, b.id).json()
    other = session.scalar(select(Vehicle).where(Vehicle.id != order.vehicle_id))
    c = AuthService(session).create_user('third-driver', 'DriverPass123!', UserRole.DRIVER)
    other.driver_user_id = c.id; session.commit()
    second = propose(client, approved(client, c), other.id, b.id).json()
    assert client.post(f"{ROOT}/substitutions/{first['id']}/confirm").status_code == 200
    assert client.post(f"{ROOT}/substitutions/{second['id']}/confirm").status_code == 409
