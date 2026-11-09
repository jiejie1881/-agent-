import type { DeliveryDemandPayload } from './delivery-demand'

export interface EntityMatch { id: number | null; method: string; candidates: { id: number; name: string; code: string }[] }
export interface DemandPreview {
  source_text: string
  data: Omit<DeliveryDemandPayload, 'date' | 'store_id' | 'period' | 'quantity'> & {
    date: string | null; store_id: number | null; period: string | null; quantity: string | number | null
  }
  sources: Record<string, string>
  store_match: EntityMatch
  missing_fields: string[]; warnings: string[]; unsupported_remark: string | null
}
export interface ParseResult { base_date: string; timezone: string; unit: string; items: DemandPreview[]; notices: string[] }
export interface QualityDimension { key: string; score: number; max_score: number; deduction: number; formula: string[]; deduction_reasons?: string[] }
export interface QualityReport {
  entities?: {plan_code: string; tasks: {order_id: number; task_code: string; vehicle: {id: number; code: string; plate_number: string; type_name: string}; driver: {id: number; employee_code: string; name: string} | null; route: {id: number; code: string; name: string}; stores: {demand_id: number; code: string; name: string}[]}[]; demands: {id: number; code: string; store_code: string; store_name: string; period: string}[]}
  id: number; plan_id: number; plan_version: number; delivery_date: string; plan_status_at_scoring: string
  generated_at: string; rule_version: string; basis_origin: string; basis_hash: string
  status: string; total_score: number | null; grade: string | null; coverage: number | null; utilization_target: number
  dimensions: QualityDimension[]; unscorable_reasons: string[]; notices: string[]
  metrics: Record<string, number>
  trips: { order_id: number; vehicle_id: number; period: string; trip_no: number; actual_load: number; max_load: number; load_ratio: number; ready: boolean; driver_readiness: { availability_status: string; message?: string } }[]
  issues: { code: string; message: string; category: string; order_id?: number; delivery_demand_id?: number }[]
  unassigned: { demand_id: number; reasons: string[] }[]
  publication_validation: string
  summary: { mode: string; text: string; suggestions: string[]; ai_commentary?: string }
}
export interface QualityComparison { comparable: boolean; notice: string; reports: QualityReport[] }
