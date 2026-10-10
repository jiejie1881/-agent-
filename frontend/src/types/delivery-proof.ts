export interface DeliveryProof {
  id: number
  url: string
  review_status: 'PENDING' | 'APPROVED' | 'REJECTED'
  replaces_proof_id: number | null
  reviews: { id: number; reviewer_username: string; decision: string; reason: string | null; created_at: string }[]
}
