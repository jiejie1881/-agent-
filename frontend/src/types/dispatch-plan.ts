import type { DeliveryDemandStatus, DeliveryPeriod } from '@/types/delivery-demand'
import type { DeliveryProof } from '@/types/delivery-proof'

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
  cargo_category_code: string
  cargo_category_name: string
  priority: 'NORMAL' | 'HIGH' | 'URGENT'
  requires_temperature_control: boolean
  min_temperature: string | null
  max_temperature: string | null
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
  cargo_category_code: string
  cargo_category_name: string
  priority: 'NORMAL' | 'HIGH' | 'URGENT'
  requires_temperature_control: boolean
  min_temperature: string | null
  max_temperature: string | null
}

export interface AutoDispatchResult {
  quality_warning?: string | null
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
  store_address: string | null
  store_longitude: string | null
  store_latitude: string | null
  quantity: string
  status: DeliveryDemandStatus
  cargo_category_code: string
  cargo_category_name: string
  priority: 'NORMAL' | 'HIGH' | 'URGENT'
  requires_temperature_control: boolean
  min_temperature: string | null
  max_temperature: string | null
  delivery_status: 'PENDING' | 'ARRIVED' | 'SIGNED' | 'FAILED'
  receiver_name: string | null
  receiver_phone: string | null
  signed_at: string | null
  driver_remark: string | null
  proofs: DeliveryProof[]
}

export interface PersistedDispatchOrder {
  id: number
  actual_driver_id?: number | null
  driver_username?: string | null
  driver_name?: string | null
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
  store_address: string | null
  store_longitude: string | null
  store_latitude: string | null
  period: DeliveryPeriod
  quantity: string
  reasons: string[]
  cargo_category_code: string
  cargo_category_name: string
  priority: 'NORMAL' | 'HIGH' | 'URGENT'
  requires_temperature_control: boolean
  min_temperature: string | null
  max_temperature: string | null
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
