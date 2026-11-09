from decimal import Decimal
import pytest
from app.models.store import Store, StoreRoute
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchPlan
from app.domain.enums import UserRole, DeliveryDemandStatus, DeliveryStopStatus, DeliveryFailureReason
from app.domain.exceptions import BusinessError
from app.schemas.auto_dispatch import AutoDispatchRequest
from app.services.auth_service import AuthService
from app.services.auto_dispatch_service import AutoDispatchService
from app.services.dispatch_plan_service import DispatchPlanService
from tests import test_agent_dispatch_foundation as foundation

def test_vehicle_and_driver_cannot_start_two_trips_at_once(session):
    admin=AuthService(session).create_user('resource-admin','BusinessPass123!',UserRole.ADMIN)
    r=foundation.resources.__wrapped__(session);r['kind'].code='BUSINESS_GENERAL'
    for index in (2,3):
        store=Store(code=f'BUSY_{index}',name=f'并发门店{index}');session.add(store);session.flush()
        session.add(StoreRoute(store_id=store.id,route_id=r['route'].id))
        session.add(DeliveryDemand(date=foundation.DAY,store_id=store.id,period='MORNING',quantity=Decimal(200),status='PENDING'))
    session.commit()
    result=AutoDispatchService(session).dispatch(AutoDispatchRequest(date=foundation.DAY),admin)
    service=DispatchPlanService(session);service.publish(result.plan_id,admin)
    plan=session.get(DispatchPlan,result.plan_id);assert len(plan.orders)==2
    first,second=plan.orders
    service.start_delivery(plan.id,first.id,r['driver'])
    with pytest.raises(BusinessError) as failure:service.start_delivery(plan.id,second.id,r['driver'])
    assert failure.value.code=='RESOURCE_IN_DELIVERY'
    assert all(d.delivery_demand.status==DeliveryDemandStatus.PUBLISHED for d in second.details)
    for detail in first.details:
        detail.delivery_status=DeliveryStopStatus.FAILED;detail.failure_reason=DeliveryFailureReason.STORE_CLOSED
    session.commit();service.complete_delivery(plan.id,first.id,r['driver'])
    service.start_delivery(plan.id,second.id,r['driver'])
    assert all(d.delivery_demand.status==DeliveryDemandStatus.DELIVERING for d in second.details)
