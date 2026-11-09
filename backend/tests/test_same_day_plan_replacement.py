from datetime import date
from unittest.mock import patch

import pytest
from app.domain.enums import DeliveryDemandStatus, DispatchPlanStatus
from app.models.audit_log import AuditLog
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchOrderDetail, DispatchPlan
from app.models.driver_scheduling import DriverAttendance, DriverSchedule
from app.models.vehicle_attendance import VehicleAttendance
from app.repositories.driver_task_repository import DriverTaskRepository
from sqlalchemy import select

from tests.test_auto_dispatch_api import create_terrain_route_and_stores, create_vehicle
from tests.test_driver_delivery_proof import PNG_1X1

DAY = '2026-10-22'


def setup_case(client, session, *, complete=True, start=True):
    terrain, _, stores = create_terrain_route_and_stores(client, [1200])
    vehicle = create_vehicle(client, terrain['id'], 'FOUR_METER', '验收货车', 1, 1500, '验收-001')
    for model in [DeliveryDemand, VehicleAttendance, DriverAttendance, DriverSchedule]:
        for row in session.scalars(select(model)):
            row.date = date.fromisoformat(DAY)
    session.commit()
    first = client.post('/api/v1/auto-dispatch', json={'date': DAY}).json()
    old_id = first['plan_id']
    assert client.post(f'/api/v1/dispatch-plans/{old_id}/publish').status_code == 200
    old = client.get(f'/api/v1/dispatch-plans/{old_id}').json()
    order_id = old['orders'][0]['id']
    stop_id = old['orders'][0]['details'][0]['id']
    login = client.post('/api/driver/auth/login', json={
        'username': f"test-driver-{vehicle['id']}", 'password': 'TestDriver123!'})
    assert login.status_code == 200
    headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
    if start:
        assert client.post(f'/api/driver/tasks/{order_id}/start', headers=headers).status_code == 200
    if complete:
        assert client.post(f'/api/driver/tasks/{order_id}/stops/{stop_id}/arrive', headers=headers).status_code == 200
        assert client.post(f'/api/driver/tasks/{order_id}/stops/{stop_id}/sign', headers=headers,
                           json={'receiver_name': '合成验收收货人'}).status_code == 200
        upload = client.post(f'/api/driver/tasks/{order_id}/stops/{stop_id}/proofs', headers=headers,
                             files={'file': ('proof.png', PNG_1X1, 'image/png')})
        assert upload.status_code == 200, upload.text
        assert client.post(f"/api/v1/delivery-proofs/{upload.json()['id']}/review",
                           json={'decision': 'APPROVED'}).status_code == 200
        assert client.post(f'/api/driver/tasks/{order_id}/complete', headers=headers).status_code == 200
    new_demand = client.post('/api/v1/delivery-demands', json={
        'date': DAY, 'store_id': stores[0][0]['id'], 'period': 'AFTERNOON',
        'quantity': 1200, 'status': 'PENDING'})
    assert new_demand.status_code == 201
    new = client.post('/api/v1/auto-dispatch', json={'date': DAY})
    assert new.status_code == 200
    return {'old': old_id, 'new': new.json()['plan_id'], 'order': order_id,
            'stop': stop_id, 'morning': stores[0][1]['id'],
            'afternoon': new_demand.json()['id'], 'headers': headers}


def snapshot_completed(session, data):
    session.expire_all()
    detail = session.get(DispatchOrderDetail, data['stop'])
    demand = session.get(DeliveryDemand, data['morning'])
    return (demand.status, demand.updated_at, detail.dispatch_order_id, detail.delivery_status,
            detail.arrived_at, detail.signed_at, detail.receiver_name,
            [(p.id, p.file_path, p.created_at, p.review_status,
              [(r.id, r.reviewer_id, r.decision, r.created_at) for r in p.reviews]) for p in detail.proofs],
            [(a.id, a.action, a.changes) for a in session.scalars(select(AuditLog).where(
                AuditLog.object_type == 'DispatchOrder', AuditLog.object_id == data['order']))])


def test_completed_morning_preserved_and_afternoon_published(client, session):
    data = setup_case(client, session)
    before = snapshot_completed(session, data)
    proof = client.get(f"/api/driver/tasks/{data['order']}", headers=data['headers']).json()['stops'][0]['proofs'][0]
    image_before = client.get(proof['url'], headers=data['headers'])
    assert image_before.status_code == 200 and image_before.content == PNG_1X1
    response = client.post(f"/api/v1/dispatch-plans/{data['new']}/publish")
    assert response.status_code == 200, response.text
    assert snapshot_completed(session, data) == before
    assert session.get(DeliveryDemand, data['afternoon']).status == DeliveryDemandStatus.PUBLISHED
    assert session.get(DispatchPlan, data['old']).status == DispatchPlanStatus.CANCELLED
    task = client.get(f"/api/driver/tasks/{data['order']}", headers=data['headers'])
    assert task.status_code == 200 and task.json()['status'] == 'COMPLETED'
    assert task.json()['stops'][0]['proofs']
    image_after = client.get(proof['url'], headers=data['headers'])
    assert image_after.status_code == 200 and image_after.content == image_before.content
    history = client.get('/api/driver/tasks/history', headers=data['headers'])
    assert history.status_code == 200
    assert data['order'] in [item['id'] for item in history.json()['items']]
    # Reopening a Session simulates reload from committed storage, not an HTTP/browser restart.
    from sqlalchemy.orm import Session
    with Session(session.get_bind()) as fresh:
        assert fresh.get(DeliveryDemand, data['morning']).status == DeliveryDemandStatus.COMPLETED
        assert DriverTaskRepository(fresh).get_for_driver(data['order'],
            fresh.get(DispatchOrderDetail, data['stop']).dispatch_order.actual_driver_id) is not None
    # Repeated publication is idempotent: one publication audit for the new plan.
    assert client.post(f"/api/v1/dispatch-plans/{data['new']}/publish").status_code == 200
    assert len(list(session.scalars(select(AuditLog).where(
        AuditLog.action == 'DISPATCH_PLAN_PUBLISHED', AuditLog.object_id == data['new'])))) == 1
    # No unauthorized restart/re-sign of historical completed work.
    assert client.post(f"/api/driver/tasks/{data['order']}/start", headers=data['headers']).status_code == 409
    assert client.get(f"/api/driver/tasks/{data['order']}").status_code == 403  # Admin is not a driver.
    assert client.post('/api/v1/driver-management/drivers', json={
        'username': 'other-driver', 'password': 'OtherDriver123!'}).status_code == 200
    other = client.post('/api/driver/auth/login', json={
        'username': 'other-driver', 'password': 'OtherDriver123!'}).json()
    assert client.get(f"/api/driver/tasks/{data['order']}", headers={
        'Authorization': 'Bearer ' + other['access_token']}).status_code == 404


@pytest.mark.parametrize('stage', ['delivering', 'arrived'])
def test_started_old_task_blocks_replacement(client, session, stage):
    data = setup_case(client, session, complete=False)
    if stage == 'arrived':
        assert client.post(f"/api/driver/tasks/{data['order']}/stops/{data['stop']}/arrive",
                           headers=data['headers']).status_code == 200
    response = client.post(f"/api/v1/dispatch-plans/{data['new']}/publish")
    assert response.status_code == 409
    session.expire_all()
    assert session.get(DispatchPlan, data['old']).status == DispatchPlanStatus.PUBLISHED
    assert session.get(DispatchPlan, data['new']).status == DispatchPlanStatus.DRAFT
    assert session.get(DeliveryDemand, data['morning']).status == DeliveryDemandStatus.DELIVERING


def test_unexecuted_omitted_demand_is_released(client, session):
    data = setup_case(client, session, complete=False, start=False)
    # Omit the morning order from the synthetic draft, retaining only the afternoon.
    plan = session.get(DispatchPlan, data['new'])
    for order in list(plan.orders):
        if any(d.delivery_demand_id == data['morning'] for d in order.details):
            session.delete(order)
    session.commit()
    assert client.post(f"/api/v1/dispatch-plans/{data['new']}/publish").status_code == 200
    session.expire_all()
    # The still-existing draft itself no longer owns morning: the published old order is released.
    assert session.get(DeliveryDemand, data['morning']).status == DeliveryDemandStatus.PENDING
    assert client.get(f"/api/driver/tasks/{data['order']}", headers=data['headers']).status_code == 404


@pytest.mark.parametrize('failure', ['validation', 'audit'])
def test_replacement_failure_rolls_back_everything(client, session, failure):
    data = setup_case(client, session)
    before = snapshot_completed(session, data)
    if failure == 'validation':
        plan = session.get(DispatchPlan, data['new'])
        plan.orders[0].total_load += 1
        session.commit()
        response = client.post(f"/api/v1/dispatch-plans/{data['new']}/publish")
        assert response.status_code == 409
    else:
        from app.models.user import User
        from app.services.dispatch_plan_service import DispatchPlanService
        actor = session.scalar(select(User).where(User.username == 'test-admin'))
        with (
            patch('app.services.dispatch_plan_service.AuditLogService.add', side_effect=RuntimeError('synthetic-audit-failure')),
            pytest.raises(RuntimeError),
        ):
            DispatchPlanService(session).publish(data['new'], actor)
    session.expire_all()
    assert snapshot_completed(session, data) == before
    assert session.get(DispatchPlan, data['old']).status == DispatchPlanStatus.PUBLISHED
    assert session.get(DispatchPlan, data['new']).status == DispatchPlanStatus.DRAFT
    assert session.get(DeliveryDemand, data['afternoon']).status == DeliveryDemandStatus.PLANNED
    assert not list(session.scalars(select(AuditLog).where(
        AuditLog.action == 'DISPATCH_PLAN_PUBLISHED', AuditLog.object_id == data['new'])))


def test_older_draft_cannot_replace_newer_publication(client, session):
    data = setup_case(client, session, complete=False, start=False)
    third = client.post('/api/v1/auto-dispatch', json={'date': DAY}).json()['plan_id']
    assert client.post(f'/api/v1/dispatch-plans/{third}/publish').status_code == 200
    response = client.post(f"/api/v1/dispatch-plans/{data['new']}/publish")
    assert response.status_code == 409
    session.expire_all()
    assert session.get(DispatchPlan, third).status == DispatchPlanStatus.PUBLISHED

