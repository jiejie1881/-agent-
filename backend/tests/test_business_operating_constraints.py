from dataclasses import replace
from collections import Counter
from datetime import date
from decimal import Decimal
import pytest
from app.domain.constraints.base import DispatchValidationContext
from app.domain.dispatch_validator import OperatingConstraint
from app.domain.enums import DeliveryPeriod
from app.dispatch_engine.dispatch_engine import DispatchEngine
from app.dispatch_engine.models import DispatchEngineInput, EngineDemand, EngineVehicle, EngineRoute
from app.dispatch_engine.priority_rules import PriorityRules
from tests import test_agent_dispatch_foundation as foundation
from app.services.dispatch_candidate_validation_service import DispatchCandidateValidator
from app.services.driver_scheduling_service import DriverSchedulingService
from app.domain.exceptions import BusinessError
from sqlalchemy import select, func

@pytest.mark.parametrize('field,code',[('vehicle_active','VEHICLE_INACTIVE'),('store_active','STORE_INACTIVE'),('route_active','ROUTE_INACTIVE'),('vehicle_route_allowed','VEHICLE_ROUTE_NOT_ALLOWED')])
def test_operating_rules_reject(field,code):
    context=DispatchValidationContext(date.today(),'车','型',DeliveryPeriod.MORNING,DeliveryPeriod.MORNING,
        Decimal(200),Decimal(100),Decimal(500),True,True,True,True,'平原',True)
    result=OperatingConstraint().validate(replace(context,**{field:False}))
    assert not result.passed and result.code==code

def engine_input():
    day=date.today()
    vehicle=EngineVehicle(1,'V','TEST',1,'BUSINESS_CUSTOM','业务车型',Decimal(1),Decimal(300),daily_trip_limit=1)
    demands=tuple(EngineDemand(i,day,i,f'S{i}',f'店{i}',DeliveryPeriod.MORNING if i<3 else DeliveryPeriod.AFTERNOON,Decimal(200)) for i in (1,2,3))
    return DispatchEngineInput(day,demands,(vehicle,),{1:EngineRoute(1,'R','线路',1,'平原')},{i:{1} for i in (1,2,3)},{(1,1)})

def test_custom_type_and_daily_limit_cover_both_periods():
    data=engine_input();result=DispatchEngine().dispatch(data)
    assert len(result.trips)==1 and len(result.unassigned_demands)==2
    assert not PriorityRules().needs_minimum_trip(data.vehicles[0],DeliveryPeriod.MORNING,Counter())

def test_allowed_routes_empty_prevents_dispatch():
    data=engine_input();result=DispatchEngine().dispatch(replace(data,vehicles=(replace(data.vehicles[0],allowed_route_ids=()),)))
    assert not result.trips and len(result.unassigned_demands)==3

def test_rated_load_changes_context_and_validator(session):
    records=foundation.resources.__wrapped__(session)
    before=foundation.context(session)
    records['vehicle'].rated_load=Decimal(150);session.commit()
    current=foundation.context(session)
    assert before.snapshot_version!=current.snapshot_version
    result=DispatchCandidateValidator().validate(foundation.candidate(current,records),current)
    assert not result.is_valid and any(v.violation_code=='OVERLOAD' for v in result.violations)

def test_maintenance_prevents_driver_start_resolution(session):
    records=foundation.resources.__wrapped__(session)
    records['vehicle'].operating_status='MAINTENANCE';session.commit()
    with pytest.raises(BusinessError):DriverSchedulingService(session).resolve(foundation.DAY,'MORNING',records['vehicle'].id)

def test_master_audit_failure_rolls_back(client,session,monkeypatch):
    from app.services.audit_log_service import AuditLogService
    from app.models.store import Store
    def fail(*args,**kwargs):raise RuntimeError('injected audit failure')
    monkeypatch.setattr(AuditLogService,'add',fail)
    with pytest.raises(RuntimeError):client.post('/api/v1/stores',json={'code':'AUDIT','name':'审计失败门店'})
    assert session.scalar(select(func.count()).select_from(Store))==0

def test_custom_vehicle_type_http(client):
    response=client.post('/api/v1/vehicle-types',json={'code':'BUSINESS_9M','name':'业务九米车型','min_load':100,'max_load':5000})
    assert response.status_code==201,response.text
    assert response.json()['code']=='BUSINESS_9M'
