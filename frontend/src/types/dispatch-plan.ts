import type { DeliveryDemandStatus, DeliveryPeriod } from '@/types/delivery-demand'

export type DispatchPlanStatus = 'DRAFT' | 'PUBLISHED' | 'CANCELLED'

export interface DispatchVehicle {
  id: number
  code: string
  plate_number: string
  vehicle_type_id: number
  vehicle_type_code: string
  vehicle_type_name: string
}

export interface DispatchRoute {
  id: number
  code: string
  name: string
  terrain_id?: number
  terrain_name?: string
}

export interface DispatchStoreAllocation {
  demand_id: number
  store_id: number
  store_code: string
  store_name: string
  quantity: string
}

export interface AutoDispatchTrip {
  vehicle: DispatchVehicle
  period: DeliveryPeriod
  trip_no: number
  route: DispatchRoute
  stores: DispatchStoreAllocation[]
  total_load: string
}

export interface AutoDispatchUnassignedDemand {
  demand_id: number
  store_id: number
  store_code: string
  store_name: string
  period: DeliveryPeriod
  quantity: string
  reasons: string[]
}

export interface AutoDispatchResult {
  plan_id: number
  date: string
  version: number
  status: DispatchPlanStatus
  trips: AutoDispatchTrip[]
  unassigned_demands: AutoDispatchUnassignedDemand[]
}

export interface DispatchPlanSummary {
  id: number
  delivery_date: string
  version: number
  status: DispatchPlanStatus
  created_at: string
  updated_at: string
}

export interface PersistedDispatchOrderDetail {
  id: number
  delivery_demand_id: number
  store_id: number
  store_code: string
  store_name: string
  quantity: string
  status: DeliveryDemandStatus
}

export interface PersistedDispatchOrder {
  id: number
  vehicle: DispatchVehicle
  period: DeliveryPeriod
  trip_no: number
  route: DispatchRoute
  total_load: string
  details: PersistedDispatchOrderDetail[]
}

export interface PersistedUnassignedDemand {
  id: number
  delivery_demand_id: number
  store_id: number
  store_code: string
  store_name: string
  period: DeliveryPeriod
  quantity: string
  reasons: string[]
}

export interface DispatchPlanDetail extends DispatchPlanSummary {
  orders: PersistedDispatchOrder[]
  unassigned_demands: PersistedUnassignedDemand[]
}

export interface DispatchPlanListItem extends DispatchPlanSummary {
  order_count: number
  assigned_demand_count: number
  unassigned_demand_count: number
}
