import type { TimestampFields } from '@/types/common'

export type VehicleTypeCode = 'FOUR_METER' | 'BIG_VAN' | 'SMALL_VAN'

export interface VehicleType extends TimestampFields {
  id: number
  code: VehicleTypeCode
  name: string
  min_load: string
  max_load: string
  is_active: boolean
}

export interface VehicleTypePayload {
  code: VehicleTypeCode
  name: string
  min_load: number
  max_load: number
  is_active: boolean
}

export interface Vehicle extends TimestampFields {
  id: number
  code: string
  plate_number: string
  vehicle_type_id: number
  is_active: boolean
  vehicle_type: VehicleType
}

export interface VehiclePayload {
  code: string
  plate_number: string
  vehicle_type_id: number
  is_active: boolean
}

export interface VehicleAttendance extends TimestampFields {
  id: number
  date: string
  vehicle_id: number
  available: boolean
  vehicle: Vehicle
}

export interface VehicleAttendanceRow {
  vehicle: Vehicle
  attendanceId: number | null
  available: boolean | null
}
