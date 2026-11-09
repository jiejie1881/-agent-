import http from '@/api/http'

export interface DriverRow {
  id: number; username: string; display_name: string | null; is_active: boolean
  default_vehicle_id: number | null; default_plate: string | null
  today_task_count: number; attendance: Record<string, boolean>
  attendance_details: Record<string, { available: boolean; source: 'ONCE' | 'FIXED' | 'UNSET'; fixed_available: boolean | null; effective_date: string | null }>
}
export interface ShiftRow {
  schedule_id: number | null; vehicle_id: number; plate_number: string
  period: string; default_driver_id: number | null; driver_id: number | null
  driver_name: string | null; kind: string | null; conflict: string | null
}
export interface LeaveRow { id: number; driver_id: number; start_date: string; end_date: string; period: string; reason: string; remark: string | null; status: string }
export interface Candidate { id: number; username: string; display_name: string | null; reason: string | null }
const root = '/driver-management'
export const fetchDrivers = (day: string) => http.get<DriverRow[]>(root + '/drivers', { params: { day } })
export const fetchShifts = (day: string) => http.get<ShiftRow[]>(root + '/workbench', { params: { day } })
export const fetchLeaves = () => http.get<LeaveRow[]>(root + '/leaves')
export const createDriver = (data: { username: string; display_name: string; password: string }) => http.post(root + '/drivers', data)
export const updateDriver = (id: number, data: { display_name?: string; is_active?: boolean }) => http.patch(`${root}/drivers/${id}`, data)
export const resetDriverPassword = (id: number, password: string) => http.post(`${root}/drivers/${id}/password`, { password })
export const bindDefaultVehicle = (id: number, vehicle_id: number | null) => http.put(`${root}/drivers/${id}/default-vehicle`, { vehicle_id })
export const setDriverAttendance = (driver_id: number, date: string, period: string, available: boolean) => http.put(root + '/attendances', { driver_id, date, period, available })
export const setFixedDriverAttendance = (driver_id: number, effective_date: string, period: string, available: boolean) => http.put(`${root}/drivers/${driver_id}/fixed-attendance`, { effective_date, period, available })
export const assignShift = (date: string, period: string, vehicle_id: number, driver_id: number | null) => http.post(root + '/schedules', { date, period, vehicle_id, driver_id })
export const fetchCandidates = (id: number) => http.get<Candidate[]>(`${root}/schedules/${id}/candidates`)
export const substituteDriver = (id: number, driver_id: number) => http.post(`${root}/schedules/${id}/substitute`, { driver_id })
export const createDriverLeave = (data: Omit<LeaveRow, 'id' | 'status'>) => http.post(root + '/leaves', data)
export const cancelDriverLeave = (id: number) => http.post(`${root}/leaves/${id}/cancel`)
