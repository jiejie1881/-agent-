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
  start_address?: string | null
  end_address?: string | null
  geographic_notes?: string | null
  distance_km?: string | null
  duration_minutes?: number | null
  route_data_source?: string | null
  id: number
  code: string
  name: string
  description: string | null
  is_active: boolean
}

export interface RoutePayload {
  start_address?: string | null
  end_address?: string | null
  geographic_notes?: string | null
  distance_km?: number | null
  duration_minutes?: number | null
  route_data_source?: string | null
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
