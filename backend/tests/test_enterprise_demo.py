from datetime import date, timedelta
from sqlalchemy import select, func
import pytest
from app.domain.enums import UserRole, DeliveryDemandStatus, DispatchPlanStatus, DeliveryStopStatus
from app.domain.exceptions import ConflictError
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.store import Store
from app.models.delivery_demand import DeliveryDemand
from app.models.cargo_category import CargoCategory
from app.models.dispatch_plan import DispatchPlan, DispatchOrderDetail
from app.models.driver_scheduling import DriverSubstitution
from app.models.ai_operations import DispatchQualityReport
from app.services.enterprise_service import EnterpriseService
from app.services.dispatch_quality_service import DispatchQualityService
from app.services.demand_entity_matching_service import DemandEntityMatchingService
from app.scripts.seed_enterprise_demo import seed_enterprise_demo, validate_target

DAY = date(2026, 11, 6)

def seed(session, history=False):
    return seed_enterprise_demo(session, DAY, 'TestOnlyDemo123', local_demo=True, prepare_history=history)

def actor(session, role=UserRole.ADMIN):
    return session.scalar(select(User).where(User.role == role))

@pytest.mark.parametrize('url,flag,expected', [
    ('mysql+pymysql://user@mysql/demo', False, 'demo'),
    ('mysql+pymysql://user@remote/demo', True, 'demo'),
    ('mysql+pymysql://user@mysql/production', True, 'production'),
    ('mysql+pymysql://user@mysql/demo', True, 'wrong'),
])
def test_seed_target_guard(url, flag, expected):
    with pytest.raises(ValueError): validate_target(url, flag, expected)

def test_seed_requires_opt_in_and_password(session):
    with pytest.raises(ValueError): seed_enterprise_demo(session, DAY, 'short', local_demo=True)
    with pytest.raises(ValueError): seed_enterprise_demo(session, DAY, 'TestOnlyDemo123')
    assert session.scalar(select(func.count()).select_from(User)) == 0

def test_foreign_date_is_rejected_before_any_write(session):
    store = Store(code='MANUAL', name='人工门店'); session.add(store); session.flush()
    category = session.scalar(select(CargoCategory).where(CargoCategory.code == 'NORMAL'))
    session.add(DeliveryDemand(date=DAY, store_id=store.id, period='MORNING', quantity=10, cargo_category_id=category.id)); session.commit()
    with pytest.raises(ConflictError): seed(session)
    assert session.scalar(select(func.count()).select_from(User)) == 0
    assert session.scalar(select(func.count()).select_from(Vehicle)) == 0

def test_seed_relationships_idempotent_and_completed_history(session):
    first = seed(session, True)
    vehicles = list(session.scalars(select(Vehicle)))
    assert len(vehicles) == len({v.code for v in vehicles}) == len({v.plate_number for v in vehicles}) == 6
    assert all(v.driver_user_id and v.driver.display_name for v in vehicles)
    assert len(list(session.scalars(select(User).where(User.role == UserRole.DRIVER)))) == 8
    counts = [session.scalar(select(func.count()).select_from(model)) for model in (User, Vehicle, DeliveryDemand, DispatchPlan, DispatchQualityReport, DriverSubstitution)]
    hashes = {u.id: u.password_hash for u in session.scalars(select(User))}
    assert seed(session, True) == first
    assert counts == [session.scalar(select(func.count()).select_from(model)) for model in (User, Vehicle, DeliveryDemand, DispatchPlan, DispatchQualityReport, DriverSubstitution)]
    assert hashes == {u.id: u.password_hash for u in session.scalars(select(User))}
    main = session.get(DispatchPlan, first['plan_ids'][0])
    assert main.status == DispatchPlanStatus.DRAFT
    assert len(main.unassigned_demands) == 1
    assert len({d.delivery_demand_id for o in main.orders for d in o.details}) == 6
    history = session.scalar(select(DispatchPlan).where(DispatchPlan.delivery_date == DAY-timedelta(days=1)))
    assert history.status == DispatchPlanStatus.PUBLISHED
    assert all(d.delivery_status == DeliveryStopStatus.SIGNED and d.delivery_demand.status == DeliveryDemandStatus.COMPLETED for o in history.orders for d in o.details)
    overview = EnterpriseService(session).overview(DAY, actor(session))
    second = next(v for v in overview['vehicles'] if v['code'] == 'ENTDEMO_VH_002')
    assert second['default_driver']['name'] == '李志强'
    assert second['shifts']['MORNING']['driver']['name'] == '赵明远'
    assert second['shifts']['AFTERNOON']['driver']['name'] == '李志强'
    assert overview['vehicles'][0]['tasks'] == []  # DRAFT is not executing.
    assert all(t['status'] == 'COMPLETED' for v in EnterpriseService(session).overview(DAY-timedelta(days=1), actor(session))['vehicles'] for t in v['tasks'])

def test_manual_changes_are_not_overwritten(session):
    result = seed(session)
    unassigned = session.get(DispatchPlan, result['plan_ids'][0]).unassigned_demands[0].delivery_demand
    unassigned.quantity = 125; session.commit()
    seed(session)
    assert unassigned.quantity == 125
    vehicle = session.scalar(select(Vehicle).where(Vehicle.code == 'ENTDEMO_VH_001'))
    vehicle.plate_number = '湘AE9999'; session.commit()
    with pytest.raises(ConflictError): seed(session)
    assert vehicle.plate_number == '湘AE9999'

def test_report_entities_are_real_and_immutable(session):
    result = seed(session)
    service = DispatchQualityService(session)
    report = service.latest(result['plan_ids'][0])
    task = report['entities']['tasks'][0]
    vehicle = session.get(Vehicle, task['vehicle']['id'])
    assert task['vehicle']['code'] == vehicle.code
    assert task['vehicle']['plate_number'] == vehicle.plate_number
    assert task['driver']['id'] is not None
    assert 'username' not in str(report['entities'])
    driver = session.get(User, task['driver']['id'])
    assert driver.display_name == task['driver']['name']
    vehicle.plate_number = '湘AE9988'; driver.display_name = '变更后姓名'; session.commit()
    assert service.latest(result['plan_ids'][0]) == report
    assert any('望城坡一店' in s for s in report['summary']['suggestions'])
    rows = list(session.scalars(select(Store)))
    match = DemandEntityMatchingService(session).match('ENTDEMO_ST_YL_001', rows)
    assert match['id'] == next(s.id for s in rows if s.code == 'ENTDEMO_ST_YL_001')

def test_enterprise_roles(client, session):
    seed(session)
    assert client.get('/api/v1/enterprise/overview', params={'day': str(DAY)}).status_code == 200
    for username, allowed in [('enterprise_viewer', True), ('enterprise_driver001', False)]:
        token = client.post('/api/v1/auth/login', json={'username': username, 'password': 'TestOnlyDemo123'}).json()['access_token']
        response = client.get('/api/v1/enterprise/overview', params={'day': str(DAY)}, headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == (200 if allowed else 403)
        if allowed:
            assert all(d['username'] is None and d['phone'] is None for d in response.json()['drivers'])

def test_demo_afternoon_adjustment_and_same_basis_comparison(session):
    from app.services.delivery_demand_service import DeliveryDemandService
    from app.schemas.delivery_demand import DeliveryDemandCreate
    from app.schemas.auto_dispatch import AutoDispatchRequest
    from app.schemas.dispatch_plan import DispatchDemandMoveRequest
    from app.services.auto_dispatch_service import AutoDispatchService
    from app.services.dispatch_plan_service import DispatchPlanService
    seed(session)
    admin = actor(session)
    for i, quantity in ((1,100),(2,100),(5,20),(6,20)):
        store = session.scalar(select(Store).where(Store.code == f'ENTDEMO_ST_YL_{i:03}'))
        DeliveryDemandService(session).create(DeliveryDemandCreate(date=DAY, store_id=store.id, period='AFTERNOON', quantity=quantity), admin)
    v2 = AutoDispatchService(session).dispatch(AutoDispatchRequest(date=DAY), admin)
    v3 = AutoDispatchService(session).dispatch(AutoDispatchRequest(date=DAY), admin)
    service = DispatchPlanService(session)
    plan = session.get(DispatchPlan, v3.plan_id)
    source = next(o for o in plan.orders if o.period.value == 'AFTERNOON' and len(o.details) == 2)
    detail = next(d for d in source.details if d.delivery_demand.store.code == 'ENTDEMO_ST_YL_005')
    target = next(o for o in plan.orders if o.period.value == 'AFTERNOON' and o.route.code == 'ENTDEMO_RT_YL_01')
    service.move_demand(plan.id, DispatchDemandMoveRequest(delivery_demand_id=detail.delivery_demand_id,source_order_id=source.id,target_order_id=target.id), admin)
    assert source.total_load == 20 and target.total_load == 120
    quality = DispatchQualityService(session)
    updated = quality.generate(plan.id, admin)
    compared = quality.compare([quality.latest(v2.plan_id)['id'], updated['id']])
    assert compared['comparable'] is True
    service.publish(plan.id, admin)
    assert plan.status == DispatchPlanStatus.PUBLISHED
