from decimal import Decimal
from sqlalchemy import select
import pytest
from app.domain.enums import UserRole
from app.domain.exceptions import BusinessError
from app.models.user import User
from app.models.dispatch_plan import DispatchPlan
from app.schemas.auto_dispatch import AutoDispatchRequest
from app.services.auto_dispatch_service import AutoDispatchService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.exception_case_service import ExceptionCaseService
from app.services.daily_exception_service import DailyExceptionService
from app.services.auth_service import AuthService
from tests import test_agent_dispatch_foundation as foundation

def test_state_conflict_requires_factual_repair_before_case_resolution(session):
    admin=AuthService(session).create_user('conflict-admin','BusinessPass123!',UserRole.ADMIN)
    foundation.resources.__wrapped__(session)
    result=AutoDispatchService(session).dispatch(AutoDispatchRequest(date=foundation.DAY),admin)
    DispatchPlanService(session).publish(result.plan_id,admin)
    plan=session.get(DispatchPlan,result.plan_id)
    detail=plan.orders[0].details[0];quantity=detail.quantity
    detail.quantity+=Decimal(1);session.commit() # Test-only corruption injection.
    report=DailyExceptionService(session).report(foundation.DAY)
    assert report['state_conflicts']['count']==1
    service=ExceptionCaseService(session)
    item=service.create('STATE_CONFLICT',detail.id,admin.id,admin)
    service.update(item.id,1,'IN_PROGRESS',admin.id,'核查数量不一致',admin)
    with pytest.raises(BusinessError,match='仍然存在'):
        service.update(item.id,2,'RESOLVED',admin.id,'不得掩盖事实',admin)
    detail.quantity=quantity;session.commit()
    assert service.update(item.id,2,'RESOLVED',admin.id,'已恢复正确数量并核对任务',admin).status=='RESOLVED'

def test_database_readiness(client):
    response=client.get('/health/ready')
    assert response.status_code==200 and response.json()['database']=='available'

def test_rejected_receipt_case_follows_multiple_immutable_replacements(session):
    from app.models.dispatch_plan import DeliveryProof
    from app.domain.enums import DeliveryStopStatus, DeliveryProofReviewStatus
    admin=AuthService(session).create_user('receipt-case-admin','BusinessPass123!',UserRole.ADMIN)
    foundation.resources.__wrapped__(session)
    result=AutoDispatchService(session).dispatch(AutoDispatchRequest(date=foundation.DAY),admin)
    DispatchPlanService(session).publish(result.plan_id,admin)
    plan=session.get(DispatchPlan,result.plan_id);detail=plan.orders[0].details[0]
    detail.delivery_status=DeliveryStopStatus.SIGNED
    def proof(name,replaces=None,status=DeliveryProofReviewStatus.REJECTED):
        item=DeliveryProof(dispatch_order_detail_id=detail.id,file_path=f'delivery-proofs/{name}.png',url=f'/uploads/delivery-proofs/{name}.png',content_type='image/png',size_bytes=1,review_status=status,replaces_proof_id=replaces)
        session.add(item);session.flush();return item
    original=proof('original');first=proof('first',original.id);latest=proof('latest',first.id,DeliveryProofReviewStatus.PENDING);session.commit()
    service=ExceptionCaseService(session);item=service.create('REJECTED_PROOF',original.id,admin.id,admin)
    service.update(item.id,1,'IN_PROGRESS',admin.id,'补传需要再次审核',admin)
    with pytest.raises(BusinessError):service.update(item.id,2,'RESOLVED',admin.id,'审核未完成，不得关闭',admin)
    latest.review_status=DeliveryProofReviewStatus.APPROVED;session.commit()
    assert service.update(item.id,2,'RESOLVED',admin.id,'最新补传版本已通过审核',admin).status=='RESOLVED'
