import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { computed, ref } from 'vue'
function setup(api, role = 'ADMIN', confirm = async () => true, listVehicles = async () => ({ data: [] })) {
  const script = readFileSync(new URL('../src/views/drivers/DriverLeaveView.vue', import.meta.url), 'utf8').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const source = ts.transpileModule(script + '\nexport { load, loading, error, leaves, admin, choose, propose, change, recommend, recommendations, day, period, openManual, manual, vehicles, vehicleId, clearRecommendations }', { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const module = { exports: {} }
  const dependencies = { vue: { ref, computed, onMounted: () => {} }, '@/api/driverLeave': api, '@/api/vehicles': { listVehicles }, '@/stores/auth': { useAuthStore: () => ({ user: { role } }) }, 'element-plus': { ElMessage: { success() {} }, ElMessageBox: { confirm } } }
  vm.runInNewContext(source, { module, exports: module.exports, require: name => dependencies[name], defineProps: () => ({}) })
  return module.exports
}
test('leave network failure clears previous rows and loading, retry succeeds', async () => {
  let failed = true
  const p = setup({ getLeaveRequests: async () => { if (failed) throw { message: '审批接口不可用' }; return { data: [{ id: 1 }] } }, getSubstitutions: async () => ({ data: [] }) })
  p.leaves.value = [{ id: 99 }]
  await p.load(); assert.equal(p.leaves.value.length, 0); assert.equal(p.loading.value, false); assert.equal(p.error.value, '审批接口不可用')
  failed = false; await p.load(); assert.equal(p.leaves.value[0].id, 1)
})
for (const role of ['ADMIN', 'DISPATCHER', 'VIEWER']) test(`${role} approval visibility`, () => { assert.equal(setup({}, role).admin.value, role === 'ADMIN') })
test('choosing candidate does not confirm; saving only creates pending proposal', async () => {
  const calls = []
  const p = setup({ proposeSubstitution: async data => calls.push(data), confirmSubstitution: async () => assert.fail('must not auto-confirm'), getLeaveRequests: async () => ({ data: [] }), getSubstitutions: async () => ({ data: [] }) })
  p.choose({ id: 10, vehicle_id: 20, start_date: '2026-10-09', period: 'MORNING' })
  assert.equal(calls.length, 0)
  await p.propose({ driver_id: 30, name: '司机' }); assert.equal(calls.length, 1); assert.equal(calls[0].substitute_driver_id, 30)
})
test('cancel confirmation does not mutate substitution', async () => {
  let calls = 0
  const p = setup({ cancelSubstitution: async () => calls++ }, 'ADMIN', async () => { throw 'cancel' })
  await p.change({ id: 1 }, true); assert.equal(calls, 0)
})

test('manual appointment loads all vehicle pages and filters inactive or unbound vehicles', async () => {
  const offsets = []
  const p = setup({}, 'ADMIN', undefined, async ({ offset }) => {
    offsets.push(offset)
    return { data: offset === 0 ? Array.from({ length: 100 }, (_, i) => ({ id: i + 1, is_active: true, driver_user_id: 1 })) : [{ id: 101, is_active: false, driver_user_id: 1 }, { id: 102, is_active: true, driver_user_id: null }] }
  })
  await p.openManual()
  assert.deepEqual(offsets, [0, 100])
  assert.equal(p.manual.value, true)
  assert.equal(p.vehicles.value.length, 100)
})

test('manual appointment saves pending without a leave and requires separate confirmation', async () => {
  const proposals = [], confirmed = []
  const p = setup({ proposeSubstitution: async data => proposals.push(data), confirmSubstitution: async id => confirmed.push(id), getLeaveRequests: async () => ({ data: [] }), getSubstitutions: async () => ({ data: [] }) })
  await p.openManual(); p.vehicleId.value = 20; p.day.value = '2026-10-10'
  await p.propose({ driver_id: 30, name: '实际司机' })
  assert.equal(proposals.length, 1)
  assert.equal('leave_request_id' in proposals[0], false)
  assert.equal(proposals[0].vehicle_id, 20)
  assert.equal(confirmed.length, 0)
  await p.change({ id: 40, status: 'PENDING' })
  assert.deepEqual(confirmed, [40])
})

test('non-admin cannot trigger manual appointment or confirmation handlers', async () => {
  for (const role of ['DISPATCHER', 'VIEWER']) {
    const p = setup({ confirmSubstitution: async () => assert.fail('not admin') }, role, undefined, async () => assert.fail('not admin'))
    await p.openManual(); await p.change({ id: 1 })
    assert.equal(p.manual.value, false)
  }
})

test('changed appointment target discards late recommendation results', async () => {
  let resolve
  const p = setup({ getRecommendations: () => new Promise(r => { resolve = r }) })
  p.choose({ id: 1, vehicle_id: 2, start_date: '2026-10-10', period: 'MORNING' })
  const pending = p.recommend()
  p.clearRecommendations()
  resolve({ data: { candidates: [{ driver_id: 3 }] } })
  await pending
  assert.equal(p.recommendations.value, null)
})
