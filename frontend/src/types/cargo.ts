import type { TimestampFields } from '@/types/common'

export interface CargoCategory extends TimestampFields {
  id: number
  code: string
  name: string
  description: string | null
  is_active: boolean
}

export interface CargoCategoryPayload {
  code: string
  name: string
  description: string | null
  is_active: boolean
}

export interface VehicleTypeCargoCapability extends TimestampFields {
  id: number
  vehicle_type_id: number
  cargo_category_id: number
  is_allowed: boolean
  min_temperature: string | null
  max_temperature: string | null
  cargo_category: CargoCategory
}

export interface VehicleTypeCargoCapabilityInput {
  cargo_category_id: number
  is_allowed: boolean
  min_temperature: number | null
  max_temperature: number | null
}
