import http from '@/api/http'
import type { CargoCategory, CargoCategoryPayload } from '@/types/cargo'

export function listCargoCategories(params: { offset?: number; limit?: number } = {}) {
  return http.get<CargoCategory[]>('/cargo-categories', { params })
}

export function createCargoCategory(data: CargoCategoryPayload) {
  return http.post<CargoCategory>('/cargo-categories', data)
}

export function updateCargoCategory(id: number, data: Partial<CargoCategoryPayload>) {
  return http.patch<CargoCategory>(`/cargo-categories/${id}`, data)
}

export function deactivateCargoCategory(id: number) {
  return http.delete<CargoCategory>(`/cargo-categories/${id}`)
}
