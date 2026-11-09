import type { DeliveryDemand } from '@/types/delivery-demand'
import type { DispatchPlanDetail, DispatchPlanSummary } from '@/types/dispatch-plan'
import type { Vehicle, VehicleAttendance } from '@/types/vehicle'

export const statusDefinitions = [
  { code: 'PENDING', label: '待计划', color: '#94a3b8' },
  { code: 'PLANNED', label: '已计划', color: '#8b5cf6' },
  { code: 'PUBLISHED', label: '已发布', color: '#2f80ed' },
  { code: 'DELIVERING', label: '配送中', color: '#f59e0b' },
  { code: 'COMPLETED', label: '已完成', color: '#10b981' },
] as const

export function selectCurrentPlan(plans: DispatchPlanSummary[]) {
  for (const status of ['PUBLISHED', 'DRAFT']) {
    const match = plans.filter(p => p.status === status).sort((a, b) => b.version - a.version)[0]
    if (match) return match
  }
  return null
}

export function demandMetrics(demands: DeliveryDemand[], plan: DispatchPlanDetail | null) {
  const valid = demands.filter(d => d.status !== 'CANCELLED')
  const ids = new Set(valid.map(d => d.id))
  const assigned = new Set(plan?.orders.flatMap(o => o.details.map(d => d.delivery_demand_id)).filter(id => ids.has(id)) ?? [])
  // Decimal quantities have two fractional digits. Add in integer hundredths.
  const quantity = valid.reduce((sum, d) => sum + Math.round(Number(d.quantity) * 100), 0) / 100
  return {
    valid, quantity, assigned: assigned.size,
    cancelled: demands.length - valid.length,
    allocationRate: !valid.length ? 0 : assigned.size / valid.length * 100,
    completionRate: !valid.length ? 0 : valid.filter(d => d.status === 'COMPLETED').length / valid.length * 100,
    statuses: statusDefinitions.map(s => ({ ...s, count: valid.filter(d => d.status === s.code).length })),
  }
}

export function fleetMetrics(vehicles: Vehicle[], attendances: VehicleAttendance[], plan: DispatchPlanDetail | null) {
  const records = new Map(attendances.map(a => [a.vehicle_id, a.available]))
  const present = vehicles.filter(v => records.get(v.id) === true)
  const available = present.filter(v => v.is_active && v.vehicle_type.is_active)
  const types = new Map<number, { id: number; code: string; name: string; total: number; present: number; trips: number }>()
  for (const vehicle of vehicles) {
    const type = vehicle.vehicle_type
    if (!types.has(type.id)) types.set(type.id, { id: type.id, code: type.code, name: type.name, total: 0, present: 0, trips: 0 })
    const row = types.get(type.id)!
    row.total++
    if (records.get(vehicle.id) === true) row.present++
  }
  for (const order of plan?.orders ?? []) {
    const row = types.get(order.vehicle.vehicle_type_id)
    if (row) row.trips++
  }
  return {
    total: vehicles.length, present: present.length, available: available.length,
    absent: vehicles.filter(v => records.get(v.id) === false).length,
    missing: vehicles.filter(v => !records.has(v.id)).length,
    types: [...types.values()],
  }
}
