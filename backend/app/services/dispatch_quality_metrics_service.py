from app.domain.enums import DeliveryDemandStatus
from app.services.daily_exception_service import DailyExceptionService
from app.services.driver_scheduling_service import DriverSchedulingService

def issue_category(code):
    if code.startswith(('DRIVER', 'SUBSTITUTE')): return 'driver'
    if code.startswith(('LOAD', 'VEHICLE_OVER', 'BELOW', 'ABOVE', 'INVALID_VEHICLE_LOAD')) or 'LOAD' in code: return 'load'
    if 'TERRAIN' in code: return 'terrain'
    if 'ROUTE' in code: return 'route'
    if 'PERIOD' in code: return 'period'
    if 'VEHICLE' in code or 'ATTENDANCE' in code: return 'vehicle'
    return 'data'

class DispatchQualityMetricsService:
    def __init__(self, session):
        self.session = session

    def collect(self, plan, scope, issues):
        scope_by_id = {item['id']: item for item in scope}
        quantity_by_id, occurrences = {}, {}
        trips, ready = [], 0
        driver_service = DriverSchedulingService(self.session)
        for order in plan.orders:
            load = sum(float(d.quantity) for d in order.details)
            maximum = float(order.vehicle.vehicle_type.max_load)
            effective = driver_service.resolve_effective_driver(order.vehicle_id, plan.delivery_date, order.period.value)
            is_ready = effective['availability_status'] == 'AVAILABLE' and effective['effective_driver_id'] == order.actual_driver_id
            ready += int(is_ready)
            trips.append({"order_id": order.id, "vehicle_id": order.vehicle_id, "period": order.period.value, "trip_no": order.trip_no, "actual_load": load, "max_load": maximum, "load_ratio": load / maximum if maximum > 0 else 0, "driver_readiness": effective, "ready": is_ready})
            for detail in order.details:
                occurrences[detail.delivery_demand_id] = occurrences.get(detail.delivery_demand_id, 0) + 1
                quantity_by_id[detail.delivery_demand_id] = quantity_by_id.get(detail.delivery_demand_id, 0) + float(detail.quantity)
        fully_assigned = {key for key, item in scope_by_id.items() if quantity_by_id.get(key, 0) >= float(item['quantity']) and occurrences.get(key) == 1}
        assigned_qty = sum(min(quantity_by_id.get(key, 0), float(item['quantity'])) for key, item in scope_by_id.items())
        unassigned = [{"demand_id": item.delivery_demand_id, "reasons": item.reasons} for item in plan.unassigned_demands if item.delivery_demand_id in scope_by_id and item.delivery_demand_id not in fully_assigned]
        represented = {d.delivery_demand_id for o in plan.orders for d in o.details} | {d.delivery_demand_id for d in plan.unassigned_demands}
        for key in scope_by_id.keys() - fully_assigned - {x['demand_id'] for x in unassigned}:
            unassigned.append({"demand_id": key, "reasons": []})
        # Explicit plan prevents cancelled/other versions from becoming the current reference.
        exceptions = DailyExceptionService(self.session).report(plan.delivery_date, plan.id, example_limit=100000)
        failure_count = exceptions['failed_stops']['count']
        documented = sum(bool(x['failure_reason']) for x in exceptions['failed_stops']['examples'])
        metrics = {"valid_demand_count": len(scope), "valid_quantity": sum(float(i['quantity']) for i in scope), "assigned_demand_count": len(fully_assigned), "assigned_quantity": assigned_qty,
            "vehicle_count": len({o.vehicle_id for o in plan.orders}), "trip_count": len(trips), "ready_trip_count": ready,
            "average_load_ratio": sum(min(max(t['load_ratio'], 0), 1) for t in trips) / len(trips) if trips else 0,
            "low_load_trip_count": sum(t['load_ratio'] < .5 for t in trips), "unassigned_count": len(scope_by_id.keys() - fully_assigned),
            "explained_unassigned_count": sum(bool(i['reasons']) and all(isinstance(r, str) and r.strip() for r in i['reasons']) for i in unassigned),
            "documented_failed_count": documented, "exception_case_count": failure_count + exceptions['plan_vehicle_unavailable']['count'] + exceptions['pending_outside_reference_plan']['count'],
            "exception_count": failure_count + exceptions['plan_vehicle_unavailable']['count'] + exceptions['pending_outside_reference_plan']['count'] + len(unassigned)}
        traces = {"version": plan.version > 0 and bool(plan.delivery_date), "scope_represented": represented == set(scope_by_id), "task_links": all(o.plan_id == plan.id and o.route_id and o.vehicle_id for o in plan.orders), "driver_snapshots": bool(plan.orders) and all(o.actual_driver_id and o.driver_username_snapshot for o in plan.orders)}
        categorized = [{**i, "category": issue_category(i['code'])} for i in issues]
        groups = {'vehicle', 'driver', 'load', 'terrain', 'route', 'period', 'data'} if plan.orders else set()
        return metrics, trips, unassigned, exceptions, traces, categorized, groups
