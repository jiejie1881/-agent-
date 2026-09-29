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
