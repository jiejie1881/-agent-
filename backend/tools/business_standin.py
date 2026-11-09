"""Deterministic test producer over supplied IDs; never imports model transport."""
import json
from decimal import Decimal
from collections import Counter
from app.agent.model_types import AgentModelResponse

class BusinessStandIn:
    async def chat(self,messages,tools):
        data=json.loads(messages[1].content)['context']
        assert tools[0]['function']['name']=='submit_dispatch_candidate'
        stores={s['id']:s for s in data['stores']}
        routes={r['id']:r for r in data['routes']}
        shifts={(s['vehicle_id'],s['period']):s for s in data['shifts']}
        permissions={tuple(p) for p in data['terrain_permissions']}
        trips=[];unassigned=[];loads=[];counts=Counter()
        for demand in data['demands']:
            if not demand['schedulable']:continue
            placed=False
            for vehicle in data['vehicles']:
                shift=shifts.get((vehicle['id'],demand['period']))
                if not (vehicle['available'] and vehicle['is_active'] and vehicle['type_active'] and vehicle['operating_status']=='ACTIVE' and shift and shift['available']):continue
                for route_id in stores[demand['store_id']]['route_ids']:
                    route=routes[route_id]
                    if not stores[demand['store_id']]['is_active'] or not route['is_active']:continue
                    if vehicle['allowed_route_ids'] is not None and route_id not in vehicle['allowed_route_ids']:continue
                    if (vehicle['vehicle_type_id'],route['terrain_id']) not in permissions:continue
                    amount=Decimal(demand['quantity']);maximum=Decimal(vehicle['max_load'])
                    if amount>maximum:continue
                    for index,trip in enumerate(trips):
                        if trip['vehicle_id']==vehicle['id'] and trip['period']==demand['period'] and trip['route_id']==route_id and loads[index]+amount<=maximum:
                            trip['demand_ids'].append(demand['id']);loads[index]+=amount;placed=True;break
                    if not placed and (vehicle['daily_trip_limit'] is None or counts[vehicle['id']]<vehicle['daily_trip_limit']):
                        trip_no=sum(t['vehicle_id']==vehicle['id'] and t['period']==demand['period'] for t in trips)+1
                        trips.append({'vehicle_id':vehicle['id'],'driver_id':shift['driver_id'],'period':demand['period'],'trip_no':trip_no,'route_id':route_id,'demand_ids':[demand['id']]})
                        loads.append(amount);counts[vehicle['id']]+=1;placed=True
                    if placed:break
                if placed:break
            if not placed:unassigned.append({'demand_id':demand['id'],'explanation':'替身未找到满足业务约束的组合'})
        return AgentModelResponse(content=json.dumps({'candidate_id':'business-standin','delivery_date':data['delivery_date'],
            'snapshot_version':data['snapshot_version'],'trips':trips,'unassigned':unassigned}))
