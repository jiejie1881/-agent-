export interface ExceptionSection<T> {
  count: number
  examples: T[]
  truncated: boolean
}

export interface DailyExceptionReport {
  receipt_issues?: ExceptionSection<{category:string;object_id:number;order_id:number;store_name:string;message:string}>
  state_conflicts?: ExceptionSection<{category:string;object_id:number;order_id:number;store_name:string;message:string}>
  delivery_date: string
  reference_plan: {
    id: number
    version: number
    status: 'DRAFT' | 'PUBLISHED' | 'CANCELLED'
    selection: string
  } | null
  plan_unassigned: ExceptionSection<{
    demand_id: number
    store_name: string
    priority: string
    reasons: string[]
  }>
  pending_outside_reference_plan: ExceptionSection<{
    demand_id: number
    store_name: string
    priority: string
    period: string
  }>
  plan_vehicle_unavailable: ExceptionSection<{
    order_id: number
    vehicle_id: number
    vehicle_plate: string
    period: string
    trip_no: number
    attendance: 'MISSING' | 'UNAVAILABLE' | 'AVAILABLE'
    issues: string[]
  }>
  failed_stops: ExceptionSection<{
    stop_id: number
    order_id: number
    demand_id: number
    store_name: string
    vehicle_plate: string
    current_driver_username: string | null
    vehicle_code?: string | null
    actual_driver_id?: number | null
    actual_driver_name?: string | null
    arrived_at: string | null
    failure_reason: string | null
  }>
  notices: string[]
  note: string
}
