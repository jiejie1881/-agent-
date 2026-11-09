from app.repositories.enterprise_repository import EnterpriseRepository
from app.services.driver_scheduling_service import DriverSchedulingService
from app.services.business_labels import driver_label, vehicle_label, reference, plan_reference
from app.domain.enums import UserRole

class EnterpriseService:
    """Read-only identity/availability view; scheduling remains the source of truth."""
    def __init__(self, session):
        self.repository = EnterpriseRepository(session)
        self.scheduling = DriverSchedulingService(session)

    def overview(self, day, actor):
        vehicles, drivers = self.repository.vehicles(), self.repository.drivers()
        users = {d.id: d for d in drivers}
        tasks = []
        for plan in self.repository.plans(day):
            for order in plan.orders:
                states = {d.delivery_demand.status.value for d in order.details}
                status = 'DELIVERING' if 'DELIVERING' in states else 'COMPLETED' if states and states <= {'COMPLETED', 'CANCELLED'} else 'PUBLISHED'
                tasks.append({'id': order.id, 'code': reference('TASK', order.id, day), 'plan_id': plan.id,
                              'plan_code': plan_reference(plan), 'vehicle_id': order.vehicle_id,
                              'driver': driver_label(order.actual_driver_id, order.driver_name_snapshot),
                              'period': order.period.value, 'trip_no': order.trip_no, 'total_load': float(order.total_load),
                              'route_code': order.route.code, 'route_name': order.route.name, 'status': status})
        attendance = self.repository.attendance(day)
        leaves, substitutions = self.repository.leaves(day), self.repository.substitutions(day)
        rows = []
        for v in vehicles:
            shifts = {}
            for period in ('MORNING', 'AFTERNOON'):
                info = self.scheduling.resolve_effective_driver(v.id, day, period)
                d = users.get(info['effective_driver_id'])
                shifts[period] = {**info, 'driver': driver_label(d.id, d.display_name) if d else None}
            rows.append({**vehicle_label(v), 'default_driver': driver_label(v.driver_user_id, v.driver.display_name if v.driver else None),
                         'attendance': attendance.get(v.id), 'shifts': shifts,
                         'tasks': [t for t in tasks if t['vehicle_id'] == v.id]})
        driver_rows = []
        for d in drivers:
            default = next((v for v in rows if v['default_driver'] and v['default_driver']['id'] == d.id), None)
            driver_rows.append({**driver_label(d.id, d.display_name), 'username': d.username if actor.role in {UserRole.ADMIN, UserRole.DISPATCHER} else None,
                                'is_active': d.is_active, 'phone': None, 'phone_notice': '当前司机模型未记录联系电话',
                                'default_vehicle': default,
                                'effective_vehicles': [{'id': v['id'], 'code': v['code'], 'plate_number': v['plate_number'], 'period': p}
                                                       for v in rows for p, s in v['shifts'].items() if s['effective_driver_id'] == d.id],
                                'attendance': {p: self.scheduling.attendance_info(day, p, d.id) for p in ('MORNING','AFTERNOON')},
                                'leaves': [{'id': l.id, 'code': reference('LV', l.id, l.start_date), 'status': l.status, 'period': l.period} for l in leaves if l.driver_id == d.id],
                                'substitutions': [{'id': s.id, 'vehicle_id': s.vehicle_id, 'status': s.status, 'period': s.period, 'as_substitute': s.substitute_driver_id == d.id} for s in substitutions if d.id in (s.original_driver_id, s.substitute_driver_id)],
                                'tasks': [t for t in tasks if t['driver'] and t['driver']['id'] == d.id]})
        return {'date': day, 'vehicles': rows, 'drivers': driver_rows,
                'notices': ['展示编号由真实主键推导，不是日内排序序号，不用于替代API主键。', '当前可调度仅表示司机/车辆/出勤条件；具体货物、线路、地形仍由正式分配校验决定。', '线路为当日已发布任务线路，不推断车辆固定所属线路。']}
