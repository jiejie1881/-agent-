import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { ref, shallowRef } from 'vue'

function load(file, dependencies = {}) {
  const source = readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const module = { exports: {} }
  vm.runInNewContext(compiled, { module, exports: module.exports, require: name => dependencies[name], Set, Map, Date, Promise }, { filename: file })
  return module.exports
}
const metrics = load('views/dashboard/metrics.ts')
const demand = (id, status = 'PENDING', quantity = '100.01', cold = false) => ({ id, status, quantity, requires_temperature_control: cold })
const detail = (ids, status = 'DRAFT') => ({ status, orders: [{ details: ids.map(delivery_demand_id => ({ delivery_demand_id })) }] })

test('published outranks later draft; cancelled is never selected', () => {
  const plans = [{ id: 1, version: 1, status: 'PUBLISHED' }, { id: 2, version: 2, status: 'DRAFT' }, { id: 3, version: 3, status: 'CANCELLED' }]
  assert.equal(metrics.selectCurrentPlan(plans).id, 1)
  assert.equal(metrics.selectCurrentPlan(plans.slice(1)).id, 2)
  assert.equal(metrics.selectCurrentPlan(plans.slice(2)), null)
})
test('latest draft is selected regardless of list order', () => {
  assert.equal(metrics.selectCurrentPlan([{ id: 1, version: 1, status: 'DRAFT' }, { id: 8, version: 8, status: 'DRAFT' }]).id, 8)
})
test('rates exclude cancelled, deduplicate allocations and ignore foreign ids', () => {
  const result = metrics.demandMetrics([demand(1), demand(2, 'COMPLETED'), demand(3, 'CANCELLED')], detail([1, 1, 3, 99]))
  assert.equal(result.assigned, 1)
  assert.equal(result.allocationRate, 50)
  assert.equal(result.completionRate, 50)
  assert.equal(result.quantity, 200.02)
})
test('empty/no-plan metrics are defined without retired temperature statistics', () => {
  assert.equal(metrics.demandMetrics([], null).completionRate, 0)
  assert.equal('cold' in metrics.demandMetrics([demand(1), demand(2)], null), false)
  assert.equal(metrics.demandMetrics([demand(1)], null).allocationRate, 0)
})
test('fleet distinguishes absent, unregistered, disabled and independent trips', () => {
  const vehicles = [1, 2, 3, 4].map(id => ({ id, is_active: id !== 4, vehicle_type: { id: 1, code: 'SMALL_VAN', name: '小包', is_active: true } }))
  const result = metrics.fleetMetrics(vehicles, [{ vehicle_id: 1, available: true }, { vehicle_id: 2, available: false }, { vehicle_id: 4, available: true }], { orders: [1, 2].map(() => ({ vehicle: { vehicle_type_id: 1 } })) })
  assert.equal(result.present, 2)
  assert.equal(result.available, 1)
  assert.equal(result.absent, 1)
  assert.equal(result.missing, 1)
  assert.equal(result.types[0].trips, 2)
})
test('pagination consumes all pages including exact-limit termination', async () => {
  const api = load('api/dashboard.ts')
  const offsets = []
  const rows = await api.collectPages(async (offset, limit) => { offsets.push(offset); return { data: Array.from({ length: offset < 200 ? limit : 0 }, (_, i) => offset + i) } })
  assert.equal(rows.length, 200)
  assert.deepEqual(offsets, [0, 100, 200])
})
test('pagination does not return partial success when a later page fails', async () => {
  const api = load('api/dashboard.ts')
  await assert.rejects(api.collectPages(async offset => { if (offset) throw new Error('network'); return { data: Array(100).fill(0) } }), /network/)
})
function dashboard(overrides = {}) {
  return load('views/dashboard/useDashboard.ts', {
    vue: { ref, shallowRef, onMounted() {}, onBeforeUnmount() {} },
    './metrics': metrics,
    '@/api/dashboard': {
      loadDashboardDemands: async () => [],
      loadDashboardFleet: async () => ({ vehicles: [], attendances: [] }),
      loadDashboardPlans: async () => [], ...overrides,
    },
    '@/api/dispatch-plans': { getDispatchPlan: async () => ({ data: null }) },
    '@/api/daily-exceptions': { getDailyExceptionReport: async () => ({ data: { reference_plan: null } }) },
  }).useDashboard()
}
test('one module failure does not suppress others and loading always ends', async () => {
  const page = dashboard({ loadDashboardDemands: async () => { throw new Error('需求加载失败') } })
  await page.load()
  assert.equal(page.demands.error.value, '需求加载失败')
  assert.ok(page.fleet.data.value)
  assert.ok(page.exceptions.data.value)
  assert.equal(page.demands.loading.value, false)
  assert.equal(page.plan.loading.value, false)
})
test('late previous-date response cannot replace current-date data', async () => {
  let finish
  const page = dashboard({ loadDashboardDemands: date => date === '2026-10-03' ? new Promise(resolve => { finish = resolve }) : Promise.resolve([demand(2)]) })
  page.date.value = '2026-10-03'
  const old = page.load()
  page.date.value = '2026-10-04'
  await page.load()
  finish([demand(1)])
  await old
  assert.equal(page.demands.data.value[0].id, 2)
})
test('refresh clears previous data before resolving or failing', async () => {
  let failed = false
  const page = dashboard({ loadDashboardDemands: async () => { if (failed) throw new Error('offline'); return [demand(1)] } })
  await page.load()
  failed = true
  const refreshing = page.load()
  assert.equal(page.demands.data.value, null)
  await refreshing
  assert.equal(page.demands.data.value, null)
  assert.equal(page.demands.error.value, 'offline')
})
