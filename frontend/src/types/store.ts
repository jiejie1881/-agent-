import type { TimestampFields } from '@/types/common'
import type { Route } from '@/types/route'

export interface Store extends TimestampFields {
  id: number
  code: string
  name: string
  address: string | null
  contact_name: string | null
  contact_phone: string | null
  longitude: string | null
  latitude: string | null
  is_active: boolean
}

export interface StorePayload {
  code: string
  name: string
  address: string | null
  contact_name: string | null
  contact_phone: string | null
  longitude: number | null
  latitude: number | null
  is_active: boolean
}

export interface StoreRoute extends TimestampFields {
  id: number
  store_id: number
  route_id: number
  route: Route
}

export interface StoreRouteDisplay extends StoreRoute {
  terrain_name: string | null
}

export interface StoreListItem extends Store {
  route_links: StoreRouteDisplay[]
}
