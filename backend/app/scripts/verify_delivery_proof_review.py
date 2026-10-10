"""Real API/MySQL review check, restricted to the disposable verification DB.

Reuses one existing signed receipt; does not change the presentation database.
"""
import base64
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.domain.enums import DeliveryProofReviewStatus, DeliveryStopStatus
from app.infrastructure.database.session import SessionLocal
from app.main import app
from app.models.audit_log import AuditLog
from app.models.dispatch_plan import DeliveryProof, DispatchOrder, DispatchOrderDetail
from app.models.user import User


def main():
    if make_url(get_settings().database_url).database != 'logistics_dispatch_demo_verify':
        raise SystemExit('Only logistics_dispatch_demo_verify is permitted')
    password = os.environ.get('DEMO_SEED_PASSWORD', '')
    if len(password) < 8:
        raise SystemExit('Set DEMO_SEED_PASSWORD locally')
    with SessionLocal() as db:
        replaced = set(db.scalars(select(DeliveryProof.replaces_proof_id).where(DeliveryProof.replaces_proof_id.is_not(None))))
        proof = next((p for p in db.scalars(select(DeliveryProof).join(DispatchOrderDetail).where(
            DispatchOrderDetail.delivery_status == DeliveryStopStatus.SIGNED,
            DeliveryProof.review_status == DeliveryProofReviewStatus.PENDING,
        ).order_by(DeliveryProof.id)) if p.id not in replaced), None)
        if proof is None:
            raise SystemExit('No unreviewed signed proof in verification database; no data was fabricated')
        order = proof.stop.dispatch_order
        actor = db.get(User, order.actual_driver_id)
        original_id, stop_id, task_id, plan_id = proof.id, proof.dispatch_order_detail_id, order.id, order.plan_id
        original_url = proof.url
        driver = actor.username
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
    report = {'database': 'logistics_dispatch_demo_verify', 'plan_id': plan_id, 'task_id': task_id, 'stop_id': stop_id, 'original_proof_id': original_id, 'checks': []}
    with TestClient(app) as client:
        tokens = {}
        other_driver = 'driver02' if driver != 'driver02' else 'driver01'
        for username in ('demo_admin', 'demo_dispatcher', driver, other_driver):
            if username in tokens:
                continue
            endpoint = '/api/driver/auth/login' if username.startswith('driver') else '/api/v1/auth/login'
            response = client.post(endpoint, json={'username': username, 'password': password})
            assert response.status_code == 200, f'Login failed for {username}'
            tokens[username] = {'Authorization': 'Bearer ' + response.json()['access_token']}

        def request(method, path, who='demo_admin', expected=200, **kwargs):
            response = client.request(method, path, headers=tokens[who], **kwargs)
            assert response.status_code == expected, f'{method} {path}: expected {expected}, got {response.status_code}: {response.text[:300]}'
            return response

        stop_path = f'/api/driver/tasks/{task_id}/stops/{stop_id}'
        task_before = request('GET', f'/api/driver/tasks/{task_id}', driver).json()
        stop_before = request('GET', stop_path, driver).json()
        assert client.get(original_url).status_code == 401
        assert request('GET', original_url, driver).headers['content-type'].startswith('image/')
        request('GET', original_url, other_driver, expected=404)
        request('GET', f'/api/v1/delivery-proofs/{original_id}/image')
        plan = request('GET', f'/api/v1/dispatch-plans/{plan_id}').json()
        stop = next(d for o in plan['orders'] for d in o['details'] if d['id'] == stop_id)
        assert stop['receiver_name'] == stop_before['receiver_name'] and stop['signed_at']
        report['checks'].append('signature metadata / authenticated image / ownership PASS')

        with SessionLocal() as db:
            audit_before = db.scalar(select(func.count(AuditLog.id)))
        review_path = f'/api/v1/delivery-proofs/{original_id}/review'
        request('POST', review_path, 'demo_dispatcher', expected=403, json={'decision': 'APPROVED'})
        request('POST', review_path, expected=422, json={'decision': 'REJECTED', 'reason': ' '})
        request('POST', stop_path + '/proofs', other_driver, expected=404, files={'file': ('other.png', png, 'image/png')})
        with SessionLocal() as db:
            assert db.scalar(select(func.count(AuditLog.id))) == audit_before
        report['checks'].append('invalid/unauthorized requests produce no success audit PASS')

        rejected = request('POST', review_path, json={'decision': 'REJECTED', 'reason': '集成验收：照片模糊，请补传'}).json()
        assert rejected['reviews'][0]['reason'] and rejected['review_status'] == 'REJECTED'
        uploaded = request('POST', stop_path + '/proofs', driver, data={'replaces_proof_id': original_id}, files={'file': ('qa-replacement.png', png, 'image/png')}).json()
        assert uploaded['replaces_proof_id'] == original_id
        assert request('GET', uploaded['url'], driver).content == png
        request('POST', stop_path + '/proofs', driver, expected=409, data={'replaces_proof_id': original_id}, files={'file': ('duplicate.png', png, 'image/png')})
        approved = request('POST', f"/api/v1/delivery-proofs/{uploaded['id']}/review", json={'decision': 'APPROVED'}).json()
        assert approved['review_status'] == 'APPROVED' and approved['reviews'][0]['decision'] == 'APPROVED'
        task_after = request('GET', f'/api/driver/tasks/{task_id}', driver).json()
        stop_after = request('GET', stop_path, driver).json()
        assert task_before['status'] == task_after['status']
        for key in ('delivery_status', 'receiver_name', 'receiver_phone', 'signed_at'):
            assert stop_before[key] == stop_after[key]
        assert {original_id, uploaded['id']}.issubset({p['id'] for p in stop_after['proofs']})
        report['checks'].append('reject / replacement / approve / preserved original & delivery status PASS')
        report['replacement_proof_id'] = uploaded['id']
        report['replacement_url'] = uploaded['url']
        with SessionLocal() as db:
            assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == 'DELIVERY_PROOF_REVIEWED', AuditLog.object_id.in_([original_id, uploaded['id']]))) == 2
            saved = db.get(DeliveryProof, uploaded['id'])
            report['replacement_file_path'] = saved.file_path
            from app.core.storage import upload_root
            assert (upload_root() / saved.file_path).read_bytes() == png
        report['checks'].append('MySQL records / local file / immutable review audit PASS')
    Path('/tmp/delivery-proof-review-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
