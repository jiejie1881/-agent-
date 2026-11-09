import http from '@/api/http'
import type {
  Vehicle,
  VehicleAttendance,
  VehiclePayload,
  VehicleType,
  VehicleTypePayload,
} from '@/types/vehicle'

export function listVehicleTypes(params: { offset?: number; limit?: number } = {}) {
  return http.get<VehicleType[]>('/vehicle-types', { params })
}

export function createVehicleType(data: VehicleTypePayload) {
  return http.post<VehicleType>('/vehicle-types', data)
}

export function updateVehicleType(
  vehicleTypeId: number,
  data: Partial<VehicleTypePayload>,
) {
  return http.patch<VehicleType>(`/vehicle-types/${vehicleTypeId}`, data)
}

export function deleteVehicleType(vehicleTypeId: number) {
  return http.delete(`/vehicle-types/${vehicleTypeId}`)
}



export function listVehicles(params: { offset?: number; limit?: number } = {}) {
  return http.get<Vehicle[]>('/vehicles', { params })
}

export function createVehicle(data: VehiclePayload) {
  return http.post<Vehicle>('/vehicles', data)
}

export function updateVehicle(vehicleId: number, data: Partial<VehiclePayload>) {
  return http.patch<Vehicle>(`/vehicles/${vehicleId}`, data)
}

export function deleteVehicle(vehicleId: number) {
  return http.delete(`/vehicles/${vehicleId}`)
}

export function listVehicleAttendances(params: {
  date: string
  vehicle_id?: number
  offset?: number
  limit?: number
}) {
  return http.get<VehicleAttendance[]>('/vehicle-attendances', { params })
}

export function createVehicleAttendance(data: {
  date: string
  vehicle_id: number
  available: boolean
}) {
  return http.post<VehicleAttendance>('/vehicle-attendances', data)
}

export function updateVehicleAttendance(
  attendanceId: number,
  data: { available: boolean },
) {
  return http.patch<VehicleAttendance>(`/vehicle-attendances/${attendanceId}`, data)
}
