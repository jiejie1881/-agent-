import http from '@/api/http'
import type { AuditLog, AuditLogQuery } from '@/types/audit-log'

export function listAuditLogs(params: AuditLogQuery = {}) {
  return http.get<AuditLog[]>('/audit-logs', { params })
}
