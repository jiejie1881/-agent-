import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { computed, ref } from 'vue'

function setup(api, canOperate = true, confirm = async () => true) {
  const source = readFileSync(new URL('../src/views/agent/AgentDispatchShadowView.vue', import.meta.url), 'utf8')
    .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const compiled = ts.transpileModule(source + '\nexport { refresh, start, saveDraft, reason, unassignedReason, context, result, error, loading, running, enabled, date }',
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const module = { exports: {} }
  const deps = { vue: { ref, computed, onMounted() {}, onBeforeUnmount() {} },
    '@/api/agent-dispatch-shadow': api, '@/stores/auth': { useAuthStore: () => ({ canOperate }) },
    'vue-router': { useRouter: () => ({ push: async () => {} }) },
    'element-plus': { ElMessageBox: { confirm } } }
  vm.runInNewContext(compiled, { module, exports: module.exports, require: name => deps[name],
    crypto: { randomUUID: () => 'fixed-test-idempotency-key' } })
  return module.exports
}

const preview = { delivery_date: '2026-11-12', snapshot_version: 'a'.repeat(64), demands: [{ id: 1, store_id: 2 }],
  stores: [{ id: 2, name: '演示门店' }], vehicles: [], routes: [], shifts: [] }

test('business preview and planning carry the same snapshot and explicit consent', async () => {
  let payload, confirmations = 0
  const page = setup({ getShadowContext: async () => ({ data: { enabled: true, context: preview } }),
    runShadowDispatch: async data => { payload = data; return { data: { status: 'SUCCESS' } } } }, true,
  async () => { confirmations++ })
  page.date.value = preview.delivery_date
  await page.refresh()
  assert.equal(page.context.value.snapshot_version, preview.snapshot_version)
  await page.start()
  assert.equal(confirmations, 1)
  assert.equal(payload.expected_snapshot_version, preview.snapshot_version)
  assert.equal(payload.authorize_external, true)
  assert.equal(payload.compare_greedy, true)
  assert.equal(page.result.value.status, 'SUCCESS')
})

test('disabled mode, viewer and cancelled consent cannot call model', async () => {
  const api = { getShadowContext: async () => ({ data: { enabled: false, reason_code: 'SHADOW_DISABLED', context: null } }),
    runShadowDispatch: () => assert.fail('model call forbidden') }
  const page = setup(api)
  await page.refresh(); await page.start()
  assert.equal(page.enabled.value, false)
  assert.match(page.error.value, /未启用/)
  const viewer = setup(api, false)
  await viewer.refresh(); await viewer.start()
  assert.equal(viewer.context.value, null)
  const cancelled = setup({ runShadowDispatch: () => assert.fail('cancelled call forbidden') }, true,
    async () => { throw 'cancel' })
  cancelled.context.value = preview; cancelled.enabled.value = true
  await cancelled.start()
  assert.equal(cancelled.running.value, false)
})

test('date refresh clears stale results and late previews cannot replace the new date', async () => {
  let resolve, n = 0
  const page = setup({ getShadowContext: () => ++n === 1 ? new Promise(r => { resolve = r }) :
    Promise.resolve({ data: { enabled: true, context: { ...preview, delivery_date: '2026-11-13' } } }) })
  const old = page.refresh()
  page.date.value = '2026-11-13'
  page.result.value = { status: 'SUCCESS' }
  await page.refresh()
  resolve({ data: { enabled: true, context: preview } }); await old
  assert.equal(page.context.value.delivery_date, '2026-11-13')
  assert.equal(page.result.value, null)
})

test('unassigned demand shows deterministic overload reason when model explanation is vague', () => {
  const page = setup({})
  page.context.value = { ...preview,
    demands: [{ id: 1, store_id: 2, quantity: '600.00', period: 'MORNING' }],
    vehicles: [{ id: 4, available: true, max_load: '500.00' }],
    shifts: [{ vehicle_id: 4, period: 'MORNING', available: true }] }
  assert.match(page.unassignedReason({ demand_id: 1, explanation: '货' }), /600.00 kg.*500 kg/)
})

test('model timeout and budget failures have clear page messages', () => {
  const page = setup({})
  assert.match(page.reason('AGENT_MODEL_TIMEOUT'), /超时/)
  assert.match(page.reason('COST_BUDGET_EXCEEDED'), /费用预算不足/)
  assert.match(page.reason('STALE_CONTEXT'), /重新读取快照/)
})

test('saving requires signed valid result and explicit separate confirmation', async () => {
  let calls = 0, confirmations = 0
  const page = setup({ acceptAgentDraft: async (candidate, receipt, key) => {
    calls++
    assert.equal(candidate.candidate_id, 'c1')
    assert.equal(receipt, 'signed-receipt')
    assert.equal(key, 'fixed-test-idempotency-key')
    return { data: { plan_id: 12 } }
  } }, true, async () => { confirmations++ })
  page.result.value = { status: 'SUCCESS', stale_context: false,
    candidate: { candidate_id: 'c1', delivery_date: '2026-11-12', trips: [], unassigned: [] },
    validation: { is_valid: true }, acceptance_receipt: null }
  await page.saveDraft()
  assert.equal(calls, 0)
  page.result.value.acceptance_receipt = 'signed-receipt'
  await page.saveDraft()
  assert.equal(confirmations, 1)
  assert.equal(calls, 1)
})
