import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { ref } from 'vue'

// Page logic with fake HTTP; not browser/real-model evidence.
function setup(api, canOperate = true, confirm = async () => true) {
  const script = readFileSync(new URL('./fixtures/AgentDispatchDemoView.vue', import.meta.url), 'utf8').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const source = ts.transpileModule(script + '\nexport { refresh, start, context, result, error, loading, running, mode, scene, inject }', { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const module = { exports: {} }
  const deps = { vue: { ref, onMounted() {}, onBeforeUnmount() {} }, '@/api/agent-dispatch-demo': api,
    '@/stores/auth': { useAuthStore: () => ({ canOperate }) }, 'element-plus': { ElMessageBox: { confirm } } }
  vm.runInNewContext(source, { module, exports: module.exports, require: name => deps[name] })
  return module.exports
}
test('context failure clears stale scene/results and ends loading', async () => {
  const p = setup({ getDemoContext: async () => { throw new Error('无法连接') } })
  p.context.value = {}; p.result.value = {}
  await p.refresh()
  assert.equal(p.context.value, null); assert.equal(p.result.value, null)
  assert.equal(p.loading.value, false); assert.equal(p.error.value, '无法连接')
})
test('late context cannot replace newly selected scene', async () => {
  let resolve, n = 0
  const p = setup({ getDemoContext: () => ++n === 1 ? new Promise(r => { resolve = r }) : Promise.resolve({ data: { context: { scene: 'new' }, real_enabled: false } }) })
  const first = p.refresh(); await p.refresh()
  resolve({ data: { context: { scene: 'old' }, real_enabled: false } }); await first
  assert.equal(p.context.value.scene, 'new')
})
test('duplicate planning is blocked and offline output renders unchanged', async () => {
  let resolve, calls = 0
  const p = setup({ runDispatchDemo: () => { calls++; return new Promise(r => { resolve = r }) } })
  p.context.value = {}; const first = p.start(); await p.start()
  assert.equal(calls, 1); assert.equal(p.running.value, true)
  resolve({ data: { mode: 'offline', result: { status: 'VALID' } } }); await first
  assert.equal(p.result.value.mode, 'offline'); assert.equal(p.running.value, false)
})
test('timeout clears previous result and releases planning lock', async () => {
  const p = setup({ runDispatchDemo: async () => { throw new Error('超时') } })
  p.context.value = {}; p.result.value = {}; await p.start()
  assert.equal(p.error.value, '超时'); assert.equal(p.result.value, null); assert.equal(p.running.value, false)
})
test('viewer cannot invoke planning', async () => {
  const p = setup({ runDispatchDemo: () => assert.fail('must not run') }, false)
  p.context.value = {}; await p.start(); assert.equal(p.running.value, false)
})
test('real consent cancellation makes no external API request', async () => {
  const p = setup({ runDispatchDemo: () => assert.fail('must not run') }, true, async () => { throw 'cancel' })
  p.context.value = {}; p.mode.value = 'real'; await p.start()
  assert.equal(p.running.value, false); assert.equal(p.error.value, '')
})
test('normal scene cannot send stale injection checkbox', async () => {
  let payload
  const p = setup({ runDispatchDemo: async data => { payload = data; return { data: {} } } })
  p.context.value = {}; p.inject.value = true; await p.start()
  assert.equal(payload.inject_violation, false); assert.equal(payload.authorize_external, false)
})
