import http from '@/api/http'
import type { Route, RoutePayload, RouteTerrainConfig } from '@/types/route'

export function listRoutes(params: { offset?: number; limit?: number } = {}) {
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
