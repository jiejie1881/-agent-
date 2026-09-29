import http from '@/api/http'
import type { Terrain, TerrainPayload } from '@/types/route'

export function listTerrains(params: { offset?: number; limit?: number } = {}) {
  return http.get<Terrain[]>('/terrains', { params })
}

export function createTerrain(data: TerrainPayload) {
  return http.post<Terrain>('/terrains', data)
}

export function updateTerrain(terrainId: number, data: Partial<TerrainPayload>) {
  return http.patch<Terrain>(`/terrains/${terrainId}`, data)
}

export function deleteTerrain(terrainId: number) {
  return http.delete(`/terrains/${terrainId}`)
}
