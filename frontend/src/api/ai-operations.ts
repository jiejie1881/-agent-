import http from './http'
import type { AIDemandPayload, ParseResult, QualityReport, QualityComparison } from '@/types/ai-operations'

export const parseDemandText = (text: string) => http.post<ParseResult>('/delivery-demands/parse-text', { text }, { timeout: 90000 })
export const confirmDemandBatch = (request_key: string, items: AIDemandPayload[]) => http.post<{ demand_ids: number[]; replayed: boolean }>('/delivery-demands/confirm-batch', { request_key, confirmed: true, items })
export const qualityHistory = (planId: number) => http.get<QualityReport[]>(`/dispatch-plans/${planId}/quality-reports`)
export const latestQualityReport = (planId: number) => http.get<QualityReport | null>(`/dispatch-plans/${planId}/quality-report`)
export const generateQualityReport = (planId: number) => http.post<QualityReport>(`/dispatch-plans/${planId}/quality-report`)
export const compareQualityReports = (report_ids: number[]) => http.post<QualityComparison>('/dispatch-plans/compare-quality', { report_ids })
export const summarizeQualityReport = (planId: number, id: number) => http.post<QualityReport['summary']>(`/dispatch-plans/${planId}/quality-reports/${id}/ai-summary`, {}, { timeout: 90000 })
