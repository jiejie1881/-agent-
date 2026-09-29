import type { TimestampFields } from '@/types/common'
import type { Store } from '@/types/store'

export type DeliveryPeriod = 'MORNING' | 'AFTERNOON'
export type DeliveryDemandStatus =
  | 'PENDING'
  | 'PLANNED'
  | 'PUBLISHED'
  | 'DELIVERING'
  | 'COMPLETED'
  | 'CANCELLED'

export interface DeliveryDemand extends TimestampFields {
  id: number
  date: string
  store_id: number
  period: DeliveryPeriod
  quantity: string
  status: DeliveryDemandStatus
  core_fields_editable: boolean
  store: Store
}

export interface DeliveryDemandPayload {
  date: string
  store_id: number
  period: DeliveryPeriod
  quantity: number
}
