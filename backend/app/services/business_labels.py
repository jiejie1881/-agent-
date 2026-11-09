"""Display references only: never replace primary keys or existing business codes."""
TYPE_NAMES = {'FOUR_METER': '4.2米厢式货车', 'BIG_VAN': '大型面包车', 'SMALL_VAN': '小型面包车'}

def reference(prefix, key, day=None):
    if key is None:
        return None
    stamp = f'{str(day).replace("-", "")}-' if day else ''
    return f'{prefix}-{stamp}{key:03d}'

def plan_reference(plan):
    return f'DP-{plan.delivery_date:%Y%m%d}-V{plan.version}'

def driver_label(key, name):
    return {'id': key, 'employee_code': reference('DRV', key), 'name': name or '姓名未填写'} if key else None

def vehicle_label(vehicle):
    return {'id': vehicle.id, 'code': vehicle.code, 'plate_number': vehicle.plate_number,
            'type_name': vehicle.vehicle_type.name,
            'type_code': vehicle.vehicle_type.code, 'max_load': float(vehicle.vehicle_type.max_load),
            'is_active': vehicle.is_active}

def quality_entities(plan, demands):
    demand_map = {d.id: d for d in demands}
    tasks = []
    for order in plan.orders:
        tasks.append({'order_id': order.id, 'task_code': reference('TASK', order.id, plan.delivery_date),
                      'vehicle': vehicle_label(order.vehicle),
                      'driver': driver_label(order.actual_driver_id, order.driver_name_snapshot),
                      'route': {'id': order.route_id, 'code': order.route.code, 'name': order.route.name},
                      'stores': [{'demand_id': d.delivery_demand_id, 'code': d.delivery_demand.store.code,
                                  'name': d.delivery_demand.store.name} for d in order.details]})
    return {'plan_code': plan_reference(plan), 'tasks': tasks,
            'demands': [{'id': d.id, 'code': reference('DEM', d.id, d.date),
                         'store_code': d.store.code, 'store_name': d.store.name, 'period': d.period.value}
                        for d in sorted(demand_map.values(), key=lambda d: d.id)]}
