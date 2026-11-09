import http from '@/api/http'
import type {
  AutoDispatchResult,
  DispatchPlanDetail,
  DispatchPlanSummary,
} from '@/types/dispatch-plan'

export function generateAutoDispatch(date: string) {
  return http.post<AutoDispatchResult>('/auto-dispatch', { date })
}

export function listDispatchPlans(params: {
  delivery_date: string
  offset?: number
  limit?: number
}) {
  return http.get<DispatchPlanSummary[]>('/dispatch-plans', { params })
}

export function getDispatchPlan(planId: number) {
  return http.get<DispatchPlanDetail>(`/dispatch-plans/${planId}`)
}

export interface AgentPublishPreview {
  can_adjust_draft: boolean
  plan_sha256: string
  plan_id: number
  delivery_date: string
  version: number
  stale: boolean
  validation_issues: { code: string; message: string }[]
  can_confirm_publish: boolean
  confirmation_receipt: string | null
}

export function getAgentPublishPreview(planId: number) {
  return http.get<AgentPublishPreview>(`/dispatch-plans/${planId}/agent-publish-preview`)
}

export function confirmAgentPublish(planId: number, receipt: string, idempotencyKey: string) {
  return http.post<DispatchPlanDetail>(`/dispatch-plans/${planId}/agent-confirm-publish`, {
    confirmation_receipt: receipt,
    confirmed: true,
  }, { headers: { 'Idempotency-Key': idempotencyKey } })
}

export function moveDispatchDemand(
  planId: number,
  data: {
    delivery_demand_id: number
    source_order_id: number
    target_order_id: number
  },
) {
  return http.post<DispatchPlanDetail>(`/dispatch-plans/${planId}/move-demand`, data)
}

export function moveAgentDispatchDemand(planId: number, data: {delivery_demand_id:number;source_order_id:number;target_order_id:number;expected_plan_sha256:string}) {
  return http.post<DispatchPlanDetail>(`/dispatch-plans/${planId}/agent-move-demand`,data)
}

export function publishDispatchPlan(planId: number) {
  return http.post<DispatchPlanDetail>(`/dispatch-plans/${planId}/publish`)
}

export function cancelDispatchPlan(planId: number) {
  return http.post<DispatchPlanDetail>(`/dispatch-plans/${planId}/cancel`)
}

export function startDispatchOrder(planId: number, orderId: number) {
  return http.post<DispatchPlanDetail>(
    `/dispatch-plans/${planId}/orders/${orderId}/start-delivery`,
  )
}

export function completeDispatchOrder(planId: number, orderId: number) {
  return http.post<DispatchPlanDetail>(
    `/dispatch-plans/${planId}/orders/${orderId}/complete`,
  )
}
