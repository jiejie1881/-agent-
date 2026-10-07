import type { TimestampFields } from '@/types/common'
import type { Store } from '@/types/store'
import type { CargoCategory } from '@/types/cargo'

export type DeliveryPeriod = 'MORNING' | 'AFTERNOON'
export type DeliveryDemandStatus =
  | 'PENDING'
  | 'PLANNED'
  | 'PUBLISHED'
  | 'DELIVERING'
  | 'COMPLETED'
  | 'CANCELLED'
export type DeliveryPriority = 'NORMAL' | 'HIGH' | 'URGENT'

export interface DeliveryDemand extends TimestampFields {
  id: number
  date: string
  store_id: number
  period: DeliveryPeriod
  quantity: string
  cargo_category_id: number
  cargo_category: CargoCategory
  priority: DeliveryPriority
  requires_temperature_control: boolean
  min_temperature: string | null
  max_temperature: string | null
  status: DeliveryDemandStatus
  core_fields_editable: boolean
  store: Store
}

export interface DeliveryDemandPayload {
  date: string
  store_id: number
  period: DeliveryPeriod
  quantity: number
  cargo_category_id: number
  priority: DeliveryPriority
  requires_temperature_control: boolean
  min_temperature: number | null
  max_temperature: number | null
}
