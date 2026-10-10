import { onMounted, onBeforeUnmount, ref, shallowRef } from 'vue'
import { loadDashboardDemands, loadDashboardFleet, loadDashboardPlans } from '@/api/dashboard'
import { getDispatchPlan } from '@/api/dispatch-plans'
import { getDailyExceptionReport } from '@/api/daily-exceptions'
import type { DeliveryDemand } from '@/types/delivery-demand'
import type { DailyExceptionReport } from '@/types/daily-exception'
import type { DispatchPlanDetail } from '@/types/dispatch-plan'
import type { Vehicle, VehicleAttendance } from '@/types/vehicle'
import { selectCurrentPlan } from './metrics'

function resource<T>() { return { data: shallowRef<T | null>(null), loading: ref(false), error: ref('') } }
export function useDashboard() {
  const now = new Date()
  const date = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`)
  const demands = resource<DeliveryDemand[]>()
  const fleet = resource<{ vehicles: Vehicle[]; attendances: VehicleAttendance[] }>()
  const plan = resource<DispatchPlanDetail | null>()
  const exceptions = resource<DailyExceptionReport>()
  const updatedAt = ref('')
  let version = 0
  async function load() {
    const queryDate = date.value
    const currentVersion = ++version
    const current = () => version === currentVersion
    updatedAt.value = ''
    async function run<T>(target: ReturnType<typeof resource<T>>, fetch: () => Promise<T>) {
      target.data.value = null
      target.error.value = ''
      target.loading.value = true
      try {
        const data = await fetch()
        if (current()) target.data.value = data
      } catch (error) {
        if (current()) target.error.value = error && typeof error === 'object' && 'message' in error ? String(error.message) : '加载失败，请重试'
      } finally { if (current()) target.loading.value = false }
    }
    await Promise.all([
      run(demands, () => loadDashboardDemands(queryDate, current)),
      run(fleet, () => loadDashboardFleet(queryDate, current)),
      run(exceptions, async () => (await getDailyExceptionReport({ date: queryDate, example_limit: 1 })).data),
      run(plan, async () => {
        const selected = selectCurrentPlan(await loadDashboardPlans(queryDate, current))
        if (!selected || !current()) return null
        return (await getDispatchPlan(selected.id)).data
      }),
    ])
    if (current()) updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  }
  onMounted(load)
  onBeforeUnmount(() => { version++ })
  return { date, demands, fleet, plan, exceptions, updatedAt, load }
}
