import type { QualityReport } from '@/types/ai-operations'
export const dimensionLabels: Record<string, string> = { allocation: '需求分配完成度', compliance: '业务约束合规性', utilization: '车辆运力利用率', readiness: '司机车辆准备度', exceptions: '未分配与异常处理', traceability: '数据完整与可追溯' }
export const percent = (value: number | undefined) => value === undefined ? '—' : `${(value * 100).toFixed(1)}%`
export const allocationRate = (r: QualityReport) => r.metrics.valid_demand_count ? r.metrics.assigned_demand_count! / r.metrics.valid_demand_count : 0
export const scoreLabel = (r: QualityReport) => r.total_score === null ? '无法评分' : `${r.total_score.toFixed(2)} / 100`
export function comparableReports(rows: QualityReport[]) {
  return rows.length >= 2 && rows.every(r => r.delivery_date === rows[0]!.delivery_date && r.rule_version === rows[0]!.rule_version && r.basis_hash === rows[0]!.basis_hash && r.utilization_target === rows[0]!.utilization_target && r.basis_origin === 'FROZEN_INPUT' && r.total_score !== null)
}
