import http from '@/api/http'
import type { Store, StorePayload, StoreRoute } from '@/types/store'

export function listStores(params: { offset?: number; limit?: number } = {}) {
  return http.get<Store[]>('/stores', { params })
}

export function createStore(data: StorePayload) {
  return http.post<Store>('/stores', data)
}

export function updateStore(storeId: number, data: Partial<StorePayload>) {
  return http.patch<Store>(`/stores/${storeId}`, data)
}

export function deleteStore(storeId: number) {
  return http.delete(`/stores/${storeId}`)
}

export function listStoreRoutes(storeId: number) {
  return http.get<StoreRoute[]>(`/stores/${storeId}/routes`)
}

export function addStoreRoute(storeId: number, routeId: number) {
  return http.post<StoreRoute>(`/stores/${storeId}/routes`, {
    route_id: routeId,
  })
}

export function removeStoreRoute(storeId: number, routeId: number) {
  return http.delete(`/stores/${storeId}/routes/${routeId}`)
}
