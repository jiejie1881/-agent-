import type { TimestampFields } from '@/types/common'

export interface Terrain extends TimestampFields {
  id: number
  code: string
  name: string
  description: string | null
  is_active: boolean
}

export interface TerrainPayload {
  code: string
  name: string
  description: string | null
  is_active: boolean
}

export interface Route extends TimestampFields {
  id: number
  code: string
  name: string
  description: string | null
  is_active: boolean
}

export interface RoutePayload {
  code: string
  name: string
  description: string | null
  is_active: boolean
}

export interface RouteTerrainConfig extends TimestampFields {
  id: number
  route_id: number
  terrain_id: number
  effective_date: string
  terrain: Terrain
}
