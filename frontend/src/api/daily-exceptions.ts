import http from '@/api/http'
import type { DailyExceptionReport } from '@/types/daily-exception'

export function getDailyExceptionReport(params: {
  date: string
  plan_id?: number
  example_limit?: number
}) {
  return http.get<DailyExceptionReport>('/daily-exceptions', { params })
}
