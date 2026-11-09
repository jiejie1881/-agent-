import http from '@/api/http'
import type { DeliveryProof } from '@/types/delivery-proof'

export async function loadProofImage(id: number) {
  const response = await http.get<Blob>(`/delivery-proofs/${id}/image`, { responseType: 'blob' })
  return URL.createObjectURL(response.data)
}

export function reviewProof(id: number, decision: 'APPROVED' | 'REJECTED', reason?: string) {
  return http.post<DeliveryProof>(`/delivery-proofs/${id}/review`, { decision, reason })
}
