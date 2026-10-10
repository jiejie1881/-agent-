import { listDeliveryDemands } from '@/api/delivery-demands'
import { listVehicleAttendances, listVehicles } from '@/api/vehicles'
import { listDispatchPlans } from '@/api/dispatch-plans'

// Array APIs have no total: keep paging until the backend returns a short page.
export async function collectPages<T>(fetchPage: (offset: number, limit: number) => Promise<{ data: T[] }>, isCurrent = () => true): Promise<T[]> {
  const rows: T[] = []
  const limit = 100
  for (let offset = 0; ; offset += limit) {
    if (!isCurrent()) throw new Error('查询日期已改变')
    const { data } = await fetchPage(offset, limit)
    rows.push(...data)
    if (data.length < limit) return rows
  }
}

export const loadDashboardDemands = (date: string, current: () => boolean) =>
  collectPages((offset, limit) => listDeliveryDemands({ date, offset, limit }), current)
export async function loadDashboardFleet(date: string, current: () => boolean) {
  const [vehicles, attendances] = await Promise.all([
    collectPages((offset, limit) => listVehicles({ offset, limit }), current),
    collectPages((offset, limit) => listVehicleAttendances({ date, offset, limit }), current),
  ])
  return { vehicles, attendances }
}
export const loadDashboardPlans = (date: string, current: () => boolean) =>
  collectPages((offset, limit) => listDispatchPlans({ delivery_date: date, offset, limit }), current)
