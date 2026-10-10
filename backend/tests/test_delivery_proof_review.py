from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.domain.enums import DeliveryDemandStatus, UserRole
from app.models.audit_log import AuditLog
from app.models.dispatch_plan import DeliveryProof, DeliveryProofReview
from app.domain.exceptions import ConflictError
from app.services.auth_service import AuthService
from tests.test_driver_api import _driver_headers, _setup_driver_tasks
from tests.test_driver_delivery_proof import PNG_1X1, _start_task


@pytest.fixture
def receipt(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr('app.services.delivery_stop_service.delivery_proof_directory', lambda: tmp_path / 'delivery-proofs')
    monkeypatch.setattr('app.services.delivery_proof_service.upload_root', lambda: tmp_path)
    _, _, order, *_ = _setup_driver_tasks(session)
    driver, task = _start_task(client, order.id)
    stop_id = task['stops'][0]['id']
    base = f'/api/driver/tasks/{order.id}/stops/{stop_id}'
    assert client.post(base + '/arrive', headers=driver).status_code == 200
    proof = client.post(base + '/proofs', headers=driver, files={'file': ('test.png', PNG_1X1, 'image/png')}).json()
    assert client.post(base + '/sign', headers=driver, json={'receiver_name': '张三', 'receiver_phone': '13800000000'}).status_code == 200
    return order, base, driver, proof, tmp_path


def test_admin_sees_signature_and_authenticated_photo(client, session, receipt):
    order, _, driver, proof, _ = receipt
    plan = client.get(f'/api/v1/dispatch-plans/{order.plan_id}').json()
    stop = next(o for o in plan['orders'] if o['id'] == order.id)['details'][0]
    assert stop['receiver_name'] == '张三' and stop['receiver_phone'] == '13800000000'
    assert stop['signed_at'] and stop['proofs'][0]['review_status'] == 'PENDING'
    for url in (proof['url'], f"/api/v1/delivery-proofs/{proof['id']}/image"):
        response = client.get(url)
        assert response.status_code == 200 and response.content == PNG_1X1
        assert response.headers['cache-control'] == 'no-store'
    assert client.get(proof['url'], headers=driver).status_code == 200


def test_photo_denies_anonymous_and_other_driver(client, session, receipt):
    _, _, _, proof, _ = receipt
    assert client.get(proof['url'], headers={'Authorization': ''}).status_code == 401
    assert client.get(proof['url'], headers=_driver_headers(client, 'driver-b')).status_code == 404
    assert client.get(f"/api/v1/delivery-proofs/{proof['id']}/image", headers=_driver_headers(client, 'driver-b')).status_code == 403


def test_approve_has_history_audit_and_preserves_delivery_state(client, session, receipt):
    order, base, driver, proof, _ = receipt
    response = client.post(f"/api/v1/delivery-proofs/{proof['id']}/review", json={'decision': 'APPROVED'})
    assert response.status_code == 200
    assert response.json()['review_status'] == 'APPROVED'
    assert response.json()['reviews'][0]['reviewer_username'] == 'test-admin'
    assert client.get(base, headers=driver).json()['delivery_status'] == 'SIGNED'
    session.refresh(order.details[0].delivery_demand)
    assert order.details[0].delivery_demand.status == DeliveryDemandStatus.DELIVERING
    assert session.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == 'DELIVERY_PROOF_REVIEWED')) == 1


@pytest.mark.parametrize('payload', [{'decision': 'REJECTED'}, {'decision': 'REJECTED', 'reason': '  '}, {'decision': 'PENDING'}])
def test_invalid_review_does_not_log_success(client, session, receipt, payload):
    proof = receipt[3]
    assert client.post(f"/api/v1/delivery-proofs/{proof['id']}/review", json=payload).status_code == 422
    assert session.scalar(select(func.count(DeliveryProofReview.id))) == 0
    assert session.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == 'DELIVERY_PROOF_REVIEWED')) == 0


def test_repeated_review_rejected_without_new_history(client, session, receipt):
    proof = receipt[3]
    url = f"/api/v1/delivery-proofs/{proof['id']}/review"
    assert client.post(url, json={'decision': 'APPROVED'}).status_code == 200
    assert client.post(url, json={'decision': 'REJECTED', 'reason': '模糊'}).status_code == 409
    assert session.scalar(select(func.count(DeliveryProofReview.id))) == 1


@pytest.mark.parametrize('role', [UserRole.DISPATCHER, UserRole.VIEWER, UserRole.DRIVER])
def test_only_admin_can_review(client, session, receipt, role):
    actor = AuthService(session).create_user('review-' + role.value, 'Password123', role)
    token = client.post('/api/v1/auth/login', json={'username': actor.username, 'password': 'Password123'}).json()['access_token']
    response = client.post(f"/api/v1/delivery-proofs/{receipt[3]['id']}/review", headers={'Authorization': 'Bearer ' + token}, json={'decision': 'APPROVED'})
    assert response.status_code == 403
    assert session.scalar(select(func.count(DeliveryProofReview.id))) == 0


def test_rejected_photo_can_be_replaced_after_task_completed(client, session, receipt):
    order, base, driver, proof, tmp_path = receipt
    assert client.post(f'/api/driver/tasks/{order.id}/complete', headers=driver).status_code == 200
    assert client.post(f"/api/v1/delivery-proofs/{proof['id']}/review", json={'decision': 'REJECTED', 'reason': '照片模糊，请重新拍摄'}).status_code == 200
    response = client.post(base + '/proofs', headers=driver, data={'replaces_proof_id': proof['id']}, files={'file': ('replacement.png', PNG_1X1, 'image/png')})
    assert response.status_code == 200
    replacement = response.json()
    assert replacement['id'] != proof['id'] and replacement['replaces_proof_id'] == proof['id']
    assert replacement['review_status'] == 'PENDING'
    assert len(list((tmp_path / 'delivery-proofs').glob('*.png'))) == 2
    assert client.get(proof['url'], headers=driver).content == PNG_1X1
    assert client.get(base, headers=driver).json()['delivery_status'] == 'SIGNED'
    session.refresh(order.details[0].delivery_demand)
    assert order.details[0].delivery_demand.status == DeliveryDemandStatus.COMPLETED
    assert client.post(f"/api/v1/delivery-proofs/{replacement['id']}/review", json={'decision': 'APPROVED'}).status_code == 200
    assert session.scalar(select(func.count(DeliveryProofReview.id))) == 2


def test_replacement_denies_other_driver_and_non_rejected_photo(client, session, receipt):
    _, base, driver, proof, _ = receipt
    upload = lambda headers: client.post(base + '/proofs', headers=headers, data={'replaces_proof_id': proof['id']}, files={'file': ('a.png', PNG_1X1, 'image/png')})
    assert upload(driver).status_code == 409
    assert upload(_driver_headers(client, 'driver-b')).status_code == 404
    assert session.scalar(select(func.count(DeliveryProof.id))) == 1


def test_replacement_only_once_and_three_current_photo_limit(client, session, receipt):
    _, base, driver, proof, _ = receipt
    for _ in range(2):
        assert client.post(base + '/proofs', headers=driver, files={'file': ('a.png', PNG_1X1, 'image/png')}).status_code == 200
    assert client.post(base + '/proofs', headers=driver, files={'file': ('a.png', PNG_1X1, 'image/png')}).status_code == 409
    client.post(f"/api/v1/delivery-proofs/{proof['id']}/review", json={'decision': 'REJECTED', 'reason': '模糊'})
    upload = lambda: client.post(base + '/proofs', headers=driver, data={'replaces_proof_id': proof['id']}, files={'file': ('a.png', PNG_1X1, 'image/png')})
    assert upload().status_code == 200
    assert upload().status_code == 409
    assert session.scalar(select(func.count(DeliveryProof.id))) == 4


def test_review_requires_signed_stop(client, session, receipt):
    order, base, driver, _, _ = receipt
    from app.domain.enums import DeliveryStopStatus
    order.details[0].delivery_status = DeliveryStopStatus.ARRIVED
    session.commit()
    proof = client.post(base + '/proofs', headers=driver, files={'file': ('a.png', PNG_1X1, 'image/png')}).json()
    assert client.post(f"/api/v1/delivery-proofs/{proof['id']}/review", json={'decision': 'APPROVED'}).status_code == 409


def test_missing_file_and_path_escape_refused(client, session, receipt):
    _, _, _, proof, root = receipt
    row = session.get(DeliveryProof, proof['id'])
    row.file_path = '../secret.png'
    session.commit()
    assert client.get(f"/api/v1/delivery-proofs/{proof['id']}/image").status_code == 404
    row.file_path = 'delivery-proofs/missing.png'
    session.commit()
    assert client.get(f"/api/v1/delivery-proofs/{proof['id']}/image").status_code == 404


def test_audit_failure_rolls_back_review(client, session, receipt, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConflictError('审计写入失败')
    monkeypatch.setattr('app.services.delivery_proof_service.AuditLogService.add', unavailable)
    proof = receipt[3]
    assert client.post(f"/api/v1/delivery-proofs/{proof['id']}/review", json={'decision': 'APPROVED'}).status_code == 409
    session.expire_all()
    assert session.get(DeliveryProof, proof['id']).review_status.value == 'PENDING'
    assert session.scalar(select(func.count(DeliveryProofReview.id))) == 0
