import http from '@/api/http'
import type {
  DeliveryDemand,
  DeliveryDemandPayload,
  DeliveryPeriod,
} from '@/types/delivery-demand'

export function listDeliveryDemands(params: {
  date: string
  store_id?: number
  period?: DeliveryPeriod
  offset?: number
  limit?: number
}) {
  return http.get<DeliveryDemand[]>('/delivery-demands', { params })
}

export function createDeliveryDemand(data: DeliveryDemandPayload) {
  return http.post<DeliveryDemand>('/delivery-demands', data)
}

export function updateDeliveryDemand(
  demandId: number,
  data: Partial<DeliveryDemandPayload>,
) {
  return http.patch<DeliveryDemand>(`/delivery-demands/${demandId}`, data)
}
