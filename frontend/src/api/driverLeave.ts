import http from '@/api/http'
export interface LeaveRequest {
  id: number; driver_id: number; driver_name: string; vehicle_id: number | null; plate_number: string | null
  start_date: string; end_date: string; period: string; leave_type: string | null; reason: string | null
  status: string; review_remark: string | null; reviewed_at: string | null; reviewed_by: number | null
}
export interface AffectedTask { task_id: number; plan_id: number; vehicle_id: number; date: string; period: string; statuses: string[]; driver_locked: boolean }
export interface Recommendation { driver_id: number; name: string; rank: number; daily_task_count: number; reasons: string[]; validated_constraints: string[] }
export interface Substitute { id: number; leave_request_id: number | null; vehicle_id: number; plate_number?: string; original_driver_id: number; original_driver_name?: string; substitute_driver_id: number; substitute_driver_name?: string; confirmed_at?: string | null; date: string; period: string; status: string }
export interface EffectiveDriver { vehicle_id: number; plate_number: string; effective_driver_id: number | null; assignment_type: string; availability_status: string; unavailable_reason: string | null; code: string | null }
const root = '/driver-management'
export const getLeaveRequests = () => http.get<LeaveRequest[]>(root + '/leave-requests')
export const getLeaveDetail = (id: number) => http.get<LeaveRequest & { affected_tasks: AffectedTask[] }>(`${root}/leave-requests/${id}`)
export const reviewLeave = (id: number, decision: 'APPROVED' | 'REJECTED', review_remark: string) => http.post(`${root}/leave-requests/${id}/review`, { decision, review_remark })
export const getRecommendations = (day: string, period: string, vehicle_id: number) => http.get<{ candidates: Recommendation[]; rejected: { driver_id: number; name: string; reason: string }[]; qualification_notice: string }>(root + '/substitution-candidates', { params: { day, period, vehicle_id } })
export const getSubstitutions = () => http.get<Substitute[]>(root + '/substitutions')
export const getEffectiveDrivers = (day: string, period: string) => http.get<EffectiveDriver[]>(root + '/effective-drivers', { params: { day, period } })
export const proposeSubstitution = (data: { leave_request_id?: number; vehicle_id: number; substitute_driver_id: number; date: string; period: string }) => http.post<Substitute>(root + '/substitutions', data)
export const confirmSubstitution = (id: number) => http.post(`${root}/substitutions/${id}/confirm`)
export const cancelSubstitution = (id: number) => http.post(`${root}/substitutions/${id}/cancel`)
