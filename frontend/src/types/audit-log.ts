export interface AuditLog {
  id: number
  user_id: number | null
  username: string
  action: string
  object_type: string
  object_id: number | null
  changes: Record<string, unknown> | null
  created_at: string
}

export interface AuditLogQuery {
  action?: string
  object_type?: string
  user_id?: number
  offset?: number
  limit?: number
}
