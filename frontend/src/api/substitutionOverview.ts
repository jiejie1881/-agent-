import * as api from './driverLeave'
import { listVehicles } from './vehicles'
import type { Vehicle } from '@/types/vehicle'

export interface SubstitutionGap {
  key: string; date: string; period: string; vehicle_id: number; plate_number: string
  reason: string; blocked: string; error: string; leave_request_id?: number
  candidates: api.Recommendation[]; rejected: { driver_id: number; name: string; reason: string }[]
  qualification_notice: string; selectedDriverId: number | null; pending: api.Substitute[]
}

export async function loadSubstitutionOverview(date: string): Promise<SubstitutionGap[]> {
  const allVehicles = async () => {
    const rows: Vehicle[] = []
    for (let offset = 0; ; offset += 100) {
      const batch = (await listVehicles({ offset, limit: 100 })).data
      rows.push(...batch)
      if (batch.length < 100) return rows
    }
  }
  const [morning, afternoon, leaves, substitutions, vehicles] = await Promise.all([
    api.getEffectiveDrivers(date, 'MORNING'), api.getEffectiveDrivers(date, 'AFTERNOON'),
    api.getLeaveRequests(), api.getSubstitutions(), allVehicles(),
  ])
  const gaps: SubstitutionGap[] = []
  for (const [period, shifts] of [['MORNING', morning.data], ['AFTERNOON', afternoon.data]] as const) {
    for (const shift of shifts) {
      if (shift.availability_status !== 'UNAVAILABLE') continue
      // 车辆不出勤/停用不是司机缺岗，不建议用换司机解决。
      if (['VEHICLE_UNAVAILABLE', 'VEHICLE_INACTIVE', 'VEHICLE_TYPE_INACTIVE'].includes(shift.code || '')) continue
      const vehicle = vehicles.find(v => v.id === shift.vehicle_id)
      const approved = leaves.data.find(l => l.driver_id === vehicle?.driver_user_id && l.status === 'APPROVED' && l.start_date <= date && l.end_date >= date && (l.period === 'ALL_DAY' || l.period === period))
      const confirmed = substitutions.data.find(s => s.vehicle_id === shift.vehicle_id && s.date === date && s.period === period && s.status === 'CONFIRMED')
      const blocked = shift.code === 'DRIVER_LEAVE_PENDING_REVIEW' ? '请先审批该班次的请假申请'
        : confirmed ? '已有已确认代班，请先核查或取消原代班；不能覆盖执行中任务'
          : !vehicle?.driver_user_id ? '请先安排常驻司机，不能用代班代替初始绑定'
            : ['DRIVER_ASSIGNMENT_STALE', 'DRIVER_ASSIGNMENT_CONFLICT'].includes(shift.code || '') ? '请先核查原排班或代班冲突' : ''
      gaps.push({ key: `${shift.vehicle_id}-${period}`, date, period, vehicle_id: shift.vehicle_id, plate_number: shift.plate_number,
        reason: shift.unavailable_reason || '司机不可用', blocked, error: '', leave_request_id: approved?.id,
        candidates: [], rejected: [], qualification_notice: '', selectedDriverId: null,
        pending: substitutions.data.filter(s => s.vehicle_id === shift.vehicle_id && s.date === date && s.period === period && s.status === 'PENDING'),
      })
    }
  }
  // 限制并发，只为真实缺岗班次请求候选，避免一次请求全部车辆的候选。
  let cursor = 0
  await Promise.all(Array.from({ length: Math.min(3, gaps.length) }, async () => {
    while (cursor < gaps.length) {
      const row = gaps[cursor++]!
      if (row.blocked) continue
      try {
        const result = (await api.getRecommendations(date, row.period, row.vehicle_id)).data
        Object.assign(row, result)
        row.selectedDriverId = result.candidates[0]?.driver_id ?? null
      } catch (e) { row.error = e instanceof Error ? e.message : e && typeof e === 'object' && 'message' in e ? String(e.message) : '候选加载失败，请刷新重试' }
    }
  }))
  return gaps
}

export async function confirmRecommendedSubstitution(row: SubstitutionGap, driverId: number) {
  // 重试使用既有待确认记录，避免确认失败后反复创建同一提案。
  let pending = row.pending.find(p => p.substitute_driver_id === driverId)
  if (!pending) {
    pending = (await api.proposeSubstitution({ vehicle_id: row.vehicle_id, date: row.date, period: row.period,
      substitute_driver_id: driverId, ...(row.leave_request_id ? { leave_request_id: row.leave_request_id } : {}) })).data
    row.pending.push(pending)
  }
  // 推荐结果不是授权；正式确认 Service 仍会重新校验并原子生效。
  return api.confirmSubstitution(pending.id)
}
