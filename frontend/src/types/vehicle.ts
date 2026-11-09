import type { TimestampFields } from '@/types/common'

export type VehicleTypeCode = string

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
  organization?: string | null
  rated_load?: string | null
  daily_trip_limit?: number | null
  operating_status?: 'ACTIVE' | 'MAINTENANCE' | 'RETIRED'
  allowed_route_ids?: number[] | null
  id: number
  code: string
  plate_number: string
  vehicle_type_id: number
  driver_user_id: number | null
  is_active: boolean
  vehicle_type: VehicleType
}

export interface VehiclePayload {
  organization?: string | null
  rated_load?: number | null
  daily_trip_limit?: number | null
  operating_status?: 'ACTIVE' | 'MAINTENANCE' | 'RETIRED'
  allowed_route_ids?: number[] | null
  code: string
  plate_number: string
  vehicle_type_id: number
  driver_user_id: number | null
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
