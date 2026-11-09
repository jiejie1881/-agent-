from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.models.audit_log import AuditLog
from app.models.dispatch_plan import DeliveryProof
from app.models.driver_operation import DriverOperationReceipt
from app.services.audit_log_service import AuditLogService
from tests.test_driver_api import _driver_headers, _setup_driver_tasks
from tests.test_driver_delivery_proof import PNG_1X1, _start_task


def scene(client,session):
    _,_,order,*_=_setup_driver_tasks(session)
    headers,task=_start_task(client,order.id)
    stop=task['stops'][0]['id']
    base=f'/api/driver/tasks/{order.id}/stops/{stop}'
    key=uuid4().hex
    first=client.post(base+'/arrive',headers={**headers,'Idempotency-Key':key})
    second=client.post(base+'/arrive',headers={**headers,'Idempotency-Key':key})
    assert first.status_code==second.status_code==200
    assert first.json()['arrived_at']==second.json()['arrived_at'] and second.json()['arrived_at'].endswith('Z')
    return headers,base


def upload(client,base,headers,key,content=PNG_1X1):
    return client.post(base+'/proofs',headers={**headers,'Idempotency-Key':key},files={'file':('test.png',content,'image/png')})


def test_lost_upload_and_signature_response_replays_once_and_keeps_permissions(client,session):
    headers,base=scene(client,session)
    key=uuid4().hex
    first=upload(client,base,headers,key)
    assert first.status_code==200
    assert upload(client,base,headers,key).json()['id']==first.json()['id']
    assert upload(client,base,headers,key,PNG_1X1+b'extra').status_code==409
    signed_key=uuid4().hex
    body={'receiver_name':'Stage6 isolated'}
    signed=client.post(base+'/sign',headers={**headers,'Idempotency-Key':signed_key},json=body)
    assert signed.status_code==200
    repeated=client.post(base+'/sign',headers={**headers,'Idempotency-Key':signed_key},json=body)
    assert repeated.status_code==200 and repeated.json()['signed_at']==signed.json()['signed_at']
    assert client.post(base+'/sign',headers={**headers,'Idempotency-Key':signed_key},json={'receiver_name':'changed'}).status_code==409
    assert client.get('/api/driver/operations/'+key,headers=headers).json()['proof_id']==first.json()['id']
    other=_driver_headers(client,'driver-b')
    assert client.get('/api/driver/operations/'+key,headers=other).status_code==404
    assert upload(client,base,other,key).status_code==404
    assert session.scalar(select(func.count()).select_from(DeliveryProof))==1
    assert session.scalar(select(func.count()).select_from(DriverOperationReceipt))==3
    assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='DELIVERY_PROOF_UPLOADED'))==1
    assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='DELIVERY_STOP_SIGNED'))==1


def test_audit_failure_rolls_back_receipt_proof_and_file_then_retry(client,session,monkeypatch):
    from app.core.storage import delivery_proof_directory
    headers,base=scene(client,session)
    key=uuid4().hex
    original=AuditLogService.add
    before=set(delivery_proof_directory().glob('*'))
    def fail(self,actor,action,*args,**kwargs):
        if action=='DELIVERY_PROOF_UPLOADED':raise RuntimeError('stage6 fault before commit')
        return original(self,actor,action,*args,**kwargs)
    monkeypatch.setattr(AuditLogService,'add',fail)
    with pytest.raises(RuntimeError,match='stage6 fault'):
        upload(client,base,headers,key)
    assert session.scalar(select(func.count()).select_from(DeliveryProof))==0
    assert session.scalar(select(func.count()).select_from(DriverOperationReceipt).where(DriverOperationReceipt.request_key==key))==0
    assert set(delivery_proof_directory().glob('*'))==before
    monkeypatch.setattr(AuditLogService,'add',original)
    assert upload(client,base,headers,key).status_code==200


@pytest.mark.parametrize('committed',[True,False])
def test_commit_outcome_unknown_never_deletes_a_committed_proof(client,session,monkeypatch,committed):
    from app.core.storage import upload_root
    headers,base=scene(client,session)
    original=session.commit
    def lost_commit_ack():
        if committed:original()
        raise OperationalError('test lost commit acknowledgement',None,Exception('test'))
    key=uuid4().hex
    monkeypatch.setattr(session,'commit',lost_commit_ack)
    assert upload(client,base,headers,key).status_code==409
    monkeypatch.setattr(session,'commit',original)
    proof=session.scalar(select(DeliveryProof))
    assert (proof is not None)==committed
    files=list((upload_root()/'delivery-proofs').glob('*'))
    assert len(files)==1
    retry=upload(client,base,headers,key)
    assert retry.status_code==200
    if committed:assert retry.json()['id']==proof.id
    assert list((upload_root()/'delivery-proofs').glob('*'))==files


def test_failure_replay_is_not_a_second_failure_event(client,session):
    headers,base=scene(client,session)
    key=uuid4().hex
    for _ in range(2):
        assert client.post(base+'/fail',headers={**headers,'Idempotency-Key':key},json={'failure_reason':'STORE_CLOSED'}).status_code==200
    assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='DELIVERY_STOP_FAILED'))==1
