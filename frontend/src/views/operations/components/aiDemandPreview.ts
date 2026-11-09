import type { DemandPreview } from '@/types/ai-operations'
import type { DeliveryDemandPayload } from '@/types/delivery-demand'

export function manualPreview(date: string): DemandPreview {
  return { source_text: '手工补充', data: { date, store_id: null, period: null, quantity: null, priority: 'NORMAL' }, sources: { date: 'MANUAL', priority: 'SYSTEM_DEFAULT' }, store_match: { id: null, method: 'MANUAL_REQUIRED', candidates: [] }, missing_fields: [], warnings: [], unsupported_remark: null }
}
export function previewErrors(row: DemandPreview): string[] {
  const d = row.data, errors: string[] = []
  if (!d.date || !/^\d{4}-\d{2}-\d{2}$/.test(d.date)) errors.push('请填写日期')
  if (!d.store_id) errors.push('请选择真实门店')
  if (!['MORNING', 'AFTERNOON'].includes(d.period ?? '')) errors.push('请选择上午/下午')
  if (d.quantity === null || !Number.isFinite(Number(d.quantity)) || Number(d.quantity) <= 0 || Number(d.quantity) >= 1e10 || !/^\d+(\.\d{1,2})?$/.test(String(d.quantity))) errors.push('请填写正数kg货量（最多两位小数）')
  return errors
}
export function previewPayload(row: DemandPreview): DeliveryDemandPayload {
  const d = row.data
  if (previewErrors(row).length) throw new Error('请补齐预览字段')
  return { date: d.date!, store_id: d.store_id!, period: d.period as DeliveryDemandPayload['period'], quantity: Number(d.quantity), priority: d.priority }
}
