import http from '@/api/http'

export interface BusinessContext {
  delivery_date: string
  snapshot_version: string
  demands: { id: number; store_id: number; quantity: string; period: string; schedulable: boolean; status: string }[]
  stores: { id: number; code: string; name: string; route_ids: number[] }[]
  vehicles: { id: number; code: string; plate_number: string; vehicle_type_name: string; min_load: string; max_load: string; available: boolean }[]
  routes: { id: number; code: string; name: string; terrain_name: string | null }[]
  shifts: { vehicle_id: number; period: string; driver_id: number | null; available: boolean; message: string | null }[]
  terrain_permissions: number[][]
}

export interface ShadowValidation {
  is_valid: boolean
  violations: { violation_code: string; message: string; related_ids: Record<string, number | string> }[]
  assigned_count: number
  unassigned_count: number
  trip_loads: string[]
  freshness_checked: boolean
}

export interface ShadowCandidate {
  candidate_id: string
  delivery_date: string
  snapshot_version: string
  trips: { vehicle_id: number; driver_id: number; route_id: number; period: string; trip_no: number; demand_ids: number[] }[]
  unassigned: { demand_id: number; explanation: string }[]
  planning_explanation: string
}

export interface ShadowMetrics {
  total_demands: number
  assigned_count: number
  unassigned_count: number
  used_vehicles: number
}

export interface ShadowResult {
  run_id: string
  acceptance_receipt: string | null
  status: 'SUCCESS' | 'REJECTED' | 'BLOCKED'
  reason_code: string
  message: string
  snapshot_version: string | null
  stale_context: boolean
  freshness_checked: boolean
  candidate: ShadowCandidate | null
  validation: ShadowValidation | null
  attempts: { generation: number; candidate: ShadowCandidate | null; validation: ShadowValidation }[]
  metrics: ShadowMetrics
  generation_count: number
  revision_count: number
  elapsed_ms: number
  comparison: { status: 'PASS' | 'BLOCKED'; metrics: ShadowMetrics | null; validation: ShadowValidation | null; error_code: string | null } | null
}

export function getShadowContext(date: string) {
  return http.get<{ enabled: boolean; reason_code: string | null; context: BusinessContext | null }>(
    '/agent/dispatch/shadow/context', { params: { delivery_date: date } },
  )
}

export function runShadowDispatch(data: { delivery_date: string; expected_snapshot_version: string; compare_greedy: boolean; authorize_external: boolean }) {
  return http.post<ShadowResult>('/agent/dispatch/shadow', data, { timeout: 130_000 })
}

export function acceptAgentDraft(candidate: ShadowCandidate, receipt: string, idempotencyKey: string) {
  return http.post<{ plan_id: number; delivery_date: string; version: number; status: 'DRAFT' | 'PUBLISHED' | 'CANCELLED' }>(
    '/agent/dispatch/accept-draft',
    { candidate, acceptance_receipt: receipt, confirmed: true },
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}
