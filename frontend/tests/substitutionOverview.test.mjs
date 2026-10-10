import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
function setup(overrides = {}, listVehicles) {
  const api = { getEffectiveDrivers: async () => ({ data: [] }), getLeaveRequests: async () => ({ data: [] }), getSubstitutions: async () => ({ data: [] }), getRecommendations: async () => ({ data: { candidates: [{ driver_id: 30, rank: 1 }], rejected: [], qualification_notice: '真实规则' } }), ...overrides }
  const source = ts.transpileModule(readFileSync(new URL('../src/api/substitutionOverview.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const module = { exports: {} }
  vm.runInNewContext(source, { module, exports: module.exports, require: name => name === './driverLeave' ? api : { listVehicles: listVehicles || (async () => ({ data: [{ id: 1, driver_user_id: 10 }] })) } })
  return module.exports
}
const gap = (id = 1, code = 'DRIVER_UNAVAILABLE') => ({ vehicle_id: id, plate_number: `车辆${id}`, availability_status: 'UNAVAILABLE', code, unavailable_reason: '司机不出勤' })

test('loads both periods and automatically recommends without writes', async () => {
  const periods = [], queries = []
  const p = setup({ getEffectiveDrivers: async (_, period) => { periods.push(period); return { data: [gap()] } }, getRecommendations: async (date, period, id) => { queries.push([date, period, id]); return { data: { candidates: [{ driver_id: 30 }], rejected: [], qualification_notice: '' } } } })
  const rows = await p.loadSubstitutionOverview('2026-10-10')
  assert.deepEqual(periods, ['MORNING', 'AFTERNOON'])
  assert.equal(queries.length, 2)
  assert.equal(rows[0].selectedDriverId, 30)
})
test('does not treat vehicle absence or healthy shifts as driver gaps', async () => {
  const p = setup({ getEffectiveDrivers: async () => ({ data: [gap(1, 'VEHICLE_UNAVAILABLE'), gap(2, 'VEHICLE_INACTIVE'), { ...gap(3), availability_status: 'AVAILABLE' }] }), getRecommendations: async () => assert.fail('no gaps') })
  assert.equal((await p.loadSubstitutionOverview('2026-10-10')).length, 0)
})
test('pending leave, existing cover and missing primary require handling not forced recommendation', async () => {
  const p = setup({ getEffectiveDrivers: async () => ({ data: [gap(1, 'DRIVER_LEAVE_PENDING_REVIEW'), gap(2), gap(3)] }), getSubstitutions: async () => ({ data: [{ vehicle_id: 2, date: '2026-10-10', period: 'MORNING', status: 'CONFIRMED' }, { vehicle_id: 2, date: '2026-10-10', period: 'AFTERNOON', status: 'CONFIRMED' }] }), getRecommendations: async () => assert.fail('blocked') }, async () => ({ data: [{ id: 1, driver_user_id: 10 }, { id: 2, driver_user_id: 20 }, { id: 3, driver_user_id: null }] }))
  const rows = await p.loadSubstitutionOverview('2026-10-10')
  assert.equal(rows.length, 6)
  assert.ok(rows.every(r => r.blocked && r.selectedDriverId === null))
})
test('approved leave matched by driver, date and shift only', async () => {
  const p = setup({ getEffectiveDrivers: async () => ({ data: [gap()] }), getLeaveRequests: async () => ({ data: [{ id: 99, driver_id: 10, status: 'CANCELLED', start_date: '2026-10-10', end_date: '2026-10-10', period: 'ALL_DAY' }, { id: 5, driver_id: 10, status: 'APPROVED', start_date: '2026-10-10', end_date: '2026-10-10', period: 'MORNING' }] }) })
  const rows = await p.loadSubstitutionOverview('2026-10-10')
  assert.equal(rows[0].leave_request_id, 5)
  assert.equal(rows[1].leave_request_id, undefined)
})
test('candidate error does not erase other shifts; no results means no selected driver', async () => {
  const p = setup({ getEffectiveDrivers: async () => ({ data: [gap()] }), getRecommendations: async (_, period) => { if (period === 'MORNING') throw { message: '候选 API 失败' }; return { data: { candidates: [], rejected: [{ name: '不可用司机', reason: '请假' }], qualification_notice: '' } } } })
  const rows = await p.loadSubstitutionOverview('2026-10-10')
  assert.equal(rows[0].error, '候选 API 失败')
  assert.equal(rows[1].selectedDriverId, null)
  assert.equal(rows[1].rejected.length, 1)
})
test('confirm failure preserves pending proposal; retry reuses it', async () => {
  let proposed = 0, confirmed = 0
  const p = setup({ proposeSubstitution: async () => { proposed++; return { data: { id: 8, substitute_driver_id: 30 } } }, confirmSubstitution: async id => { assert.equal(id, 8); confirmed++; if (confirmed === 1) throw Error('新冲突'); return {} } })
  const row = { date: '2026-10-10', period: 'MORNING', vehicle_id: 1, pending: [] }
  await assert.rejects(p.confirmRecommendedSubstitution(row, 30), /新冲突/)
  await p.confirmRecommendedSubstitution(row, 30)
  assert.equal(proposed, 1)
  assert.equal(confirmed, 2)
})
test('candidate requests are concurrency bounded and all vehicles paginated', async () => {
  let active = 0, max = 0
  const offsets = []
  const p = setup({ getEffectiveDrivers: async () => ({ data: Array.from({ length: 5 }, (_, i) => gap(i + 1)) }), getRecommendations: async () => { active++; max = Math.max(max, active); await new Promise(r => setTimeout(r, 5)); active--; return { data: { candidates: [], rejected: [], qualification_notice: '' } } } }, async ({ offset }) => { offsets.push(offset); return { data: offset === 0 ? Array.from({ length: 100 }, (_, i) => ({ id: i + 1, driver_user_id: 10 })) : [] } })
  const rows = await p.loadSubstitutionOverview('2026-10-10')
  assert.deepEqual(offsets, [0, 100])
  assert.equal(rows.length, 10)
  assert.ok(max <= 3)
})
