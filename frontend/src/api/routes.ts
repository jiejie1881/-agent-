import http from '@/api/http'
import type {Store} from '@/types/store'
export const listRouteStores = (id:number) => http.get<Store[]>(`/routes/${id}/stores`)
import type { Route, RoutePayload, RouteTerrainConfig } from '@/types/route'

export function listRoutes(params: { offset?: number; limit?: number; q?:string; is_active?:boolean } = {}) {
  return http.get<Route[]>('/routes', { params })
}

export function listRouteTerrainConfigs(routeId: number) {
  return http.get<RouteTerrainConfig[]>(`/routes/${routeId}/terrain-configs`)
}

export function createRoute(data: RoutePayload) {
  return http.post<Route>('/routes', data)
}

export function updateRoute(routeId: number, data: Partial<RoutePayload>) {
  return http.patch<Route>(`/routes/${routeId}`, data)
}

export function deleteRoute(routeId: number) {
  return http.delete(`/routes/${routeId}`)
}
