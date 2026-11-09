import http from '@/api/http'

export interface DemoContext {
  delivery_date: string
  snapshot_version: string
  demands: { id: number; quantity: string; period: string; store_id: number }[]
  vehicles: { id: number; code: string; vehicle_type_name: string; min_load: string; max_load: string; available: boolean }[]
  routes: { id: number; name: string; terrain_id: number; terrain_name: string }[]
  terrain_permissions: number[][]
}
export interface DemoCandidate {
  trips: { vehicle_id: number; driver_id: number; route_id: number; trip_no: number; period: string; demand_ids: number[] }[]
  unassigned: { demand_id: number; explanation: string }[]
  planning_explanation: string
}
export interface DemoValidation {
  is_valid: boolean
  violations: { violation_code: string; message: string; related_ids: Record<string, string | number> }[]
}
export interface DemoResult {
  mode: string
  injection: boolean
  context: DemoContext
  persistence: string
  result: {
    run_id: string; status: string; reason_code: string; message: string
    elapsed_ms: number; revision_count: number; generation_count: number
    freshness_checked: boolean; stale_context: boolean; snapshot_version: string | null
    candidate: DemoCandidate | null; validation: DemoValidation | null
    token_usage: { total_tokens: number } | null
    estimated_cost: string | null; cost_currency: string | null
    attempts: { generation: number; candidate: DemoCandidate | null; validation: DemoValidation }[]
  }
}
export type Scene = 'normal' | 'overweight' | 'terrain'
export function getDemoContext(scene: Scene, date: string) {
  return http.get<{ context: DemoContext; real_enabled: boolean }>('/agent/dispatch/demo/context', { params: { scene, delivery_date: date } })
}
export function runDispatchDemo(data: { scene: Scene; delivery_date: string; mode: 'offline' | 'real'; inject_violation: boolean; authorize_external: boolean }) {
  return http.post<DemoResult>('/agent/dispatch/demo', data, { timeout: 130_000 })
}
