import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { computed, ref } from 'vue'

// Deterministic page-logic tests with mocked APIs, not browser E2E.
function setup(api = {}, role = 'ADMIN', confirm = async () => true) {
  const script = readFileSync(new URL('../src/views/agent/AgentChatView.vue', import.meta.url), 'utf8').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const source = ts.transpileModule(script + '\nexport { handleConfirmAction, handleCancelAction, selectConversation, sendMessage, input, sending, actionLoadingId, interactionLocked, currentConversationId, currentConversation, handleResumeExecution, resumeLoadingId, executions, mergeExecutionReports, refreshExecutions, executionStatusError, reloadCurrentConversation, sendBlocked }', { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const module = { exports: {} }
  const timers = new Map()
  let timerId = 0, unmount = () => {}
  const dependencies = {
    vue: { computed, ref, nextTick: async () => {}, onMounted() {}, onBeforeUnmount(fn) { unmount = fn } },
    '@/api/agent': api,
    '@/stores/auth': { useAuthStore: () => ({ canOperate: ['ADMIN', 'DISPATCHER'].includes(role) }) },
    'element-plus': { ElMessage: { success() {} }, ElMessageBox: { confirm } },
  }
  vm.runInNewContext(source, { module, exports: module.exports, require: name => dependencies[name] || {},
    AbortController,
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id }, clearTimeout(id) { timers.delete(id) } })
  const p = module.exports
  p.timerCount = () => timers.size
  p.unmount = () => unmount()
  p.currentConversationId.value = 10
  p.currentConversation.value = { id: 10, messages: [{ content: '已有历史' }], pending_actions: [] }
  return p
}

const report = (changes = {}) => ({
  execution_id: 'owned-execution', conversation_id: 10, intent: 'VEHICLES', status: 'FAILED', current_node: 'tools',
  plan: [], events: [{ node: 'tools', status: 'FAILED' }], completed_steps: 0, tool_attempts: 1, replans: 0,
  elapsed_ms: 10, revision: 1, can_resume: true, ...changes,
})

// The page starts its polling request without blocking the conversation read.
// Flush the VM promise chain through the next event-loop turn before checking
// the scheduled timer; one Promise.resolve() does not drain nested awaits.
const flushPageTasks = () => new Promise(resolve => setImmediate(resolve))

test('duplicate send is blocked while first request is unresolved', async () => {
  let resolve, sends = 0
  const p = setup({ sendConversationMessage: () => { sends++; return new Promise(r => { resolve = r }) },
    getAgentExecutions: async () => ({ data: [] }), getConversation: async () => ({ data: { id: 10, messages: [] } }),
    listConversations: async () => ({ data: [] }) })
  p.input.value = '查询车辆'
  const first = p.sendMessage()
  await p.sendMessage()
  assert.equal(sends, 1)
  resolve({ data: {} }); await first
  p.unmount()
})

test('resume is gated by the authoritative report and locks duplicate actions', async () => {
  let resolve, resumes = 0
  const failed = report()
  const p = setup({ resumeAgentExecution: () => { resumes++; return new Promise(r => { resolve = r }) },
    getAgentExecutions: async () => ({ data: [failed] }), getConversation: async () => ({ data: { id: 10, messages: [] } }) })
  await p.handleResumeExecution(failed)
  assert.equal(resumes, 0)
  p.executions.value = [failed]
  const first = p.handleResumeExecution(failed)
  assert.equal(p.interactionLocked.value, true)
  await p.handleResumeExecution(failed)
  await p.handleConfirmAction(action)
  assert.equal(resumes, 1)
  resolve({ data: report({ status: 'COMPLETED', can_resume: false, revision: 2 }) }); await first
  assert.equal(p.resumeLoadingId.value, null)
  assert.equal(p.executions.value[0].status, 'COMPLETED')
  p.unmount()
})

test('resume response loss reconciles without automatic replay', async () => {
  let resumes = 0, reads = 0
  const p = setup({ resumeAgentExecution: async () => { resumes++; throw { status: 'timeout' } },
    getAgentExecutions: async () => ({ data: [report({ status: 'COMPLETED', can_resume: false, revision: 3 })] }),
    getConversation: async () => { reads++; return { data: { id: 10, messages: [] } } } })
  p.executions.value = [report()]
  await p.handleResumeExecution(report())
  assert.equal(resumes, 1); assert.equal(reads, 1)
  assert.equal(p.executions.value[0].status, 'COMPLETED')
  assert.equal(p.resumeLoadingId.value, null)
  p.unmount()
})

test('stale local resume argument cannot override server can_resume false', async () => {
  const p = setup({ resumeAgentExecution: () => assert.fail('resume') })
  p.executions.value = [report({ can_resume: false })]
  await p.handleResumeExecution(report())
  assert.equal(p.resumeLoadingId.value, null)
})

for (const status of ['RUNNING', 'RECOVERING', 'RETRYING']) {
  test(`backend ${status} blocks another send without locking conversation navigation`, async () => {
    const p = setup({ sendConversationMessage: () => assert.fail('duplicate send'),
      getConversation: async id => ({ data: { id, messages: [] } }), getAgentExecutions: async () => ({ data: [] }) })
    p.executions.value = [report({ status, can_resume: false })]
    p.input.value = '重复业务请求'
    assert.equal(p.sendBlocked.value, true)
    assert.equal(p.interactionLocked.value, false)
    await p.sendMessage()
    await p.selectConversation(11)
    assert.equal(p.currentConversationId.value, 11)
    assert.equal(p.sendBlocked.value, false)
  })
}

test('a server-recoverable report does not lock new input or fabricate progress', () => {
  const p = setup()
  p.executions.value = [report({ status: 'RUNNING', can_resume: true })]
  assert.equal(p.sendBlocked.value, false)
  assert.equal(p.executions.value[0].status, 'RUNNING')
})

test('lower revision with equal events cannot replace a completed execution', () => {
  const p = setup()
  p.executions.value = [report({ status: 'COMPLETED', revision: 4, can_resume: false })]
  p.mergeExecutionReports([report({ status: 'RUNNING', revision: 3 })])
  assert.equal(p.executions.value[0].status, 'COMPLETED')
  assert.equal(p.executions.value[0].revision, 4)
})

test('newer revision may safely enter recovery even with fewer events', () => {
  const p = setup()
  p.executions.value = [report({ revision: 2 })]
  p.mergeExecutionReports([report({ status: 'RECOVERING', revision: 3, events: [] })])
  assert.equal(p.executions.value[0].status, 'RECOVERING')
  assert.equal(p.executions.value[0].revision, 3)
})

test('a stale poll missing the new execution cannot hide its active send barrier', () => {
  const p = setup()
  p.executions.value = [report({ execution_id: 'new-execution', status: 'RUNNING', can_resume: false }), report({ status: 'COMPLETED' })]
  p.mergeExecutionReports([report({ status: 'COMPLETED' })])
  assert.equal(p.executions.value[0].execution_id, 'new-execution')
  assert.equal(p.sendBlocked.value, true)
})

test('a fresh execution may lead a full server list while old retained reports fall behind', () => {
  const p = setup()
  p.executions.value = [report({ status: 'COMPLETED' })]
  p.mergeExecutionReports([report({ execution_id: 'new-execution', status: 'RUNNING', can_resume: false })])
  assert.equal(p.executions.value[0].execution_id, 'new-execution')
  assert.equal(p.sendBlocked.value, true)
})

test('legacy reports without revision retain terminal progress over old running snapshot', () => {
  const p = setup()
  p.executions.value = [report({ status: 'COMPLETED', revision: undefined })]
  p.mergeExecutionReports([report({ status: 'RUNNING', revision: undefined })])
  assert.equal(p.executions.value[0].status, 'COMPLETED')
})

test('poll failure preserves the last record and exposes an explicit stale-state warning', async () => {
  let failed = true
  const p = setup({ getAgentExecutions: async () => { if (failed) throw { status: 0 }; return { data: [report({ revision: 2 })] } } })
  p.executions.value = [report()]
  await p.refreshExecutions(10)
  assert.equal(p.executionStatusError.value, true)
  assert.equal(p.executions.value[0].revision, 1)
  failed = false; await p.refreshExecutions(10)
  assert.equal(p.executionStatusError.value, false)
  assert.equal(p.executions.value[0].revision, 2)
})

for (const status of ['RUNNING', 'RECOVERING', 'RETRYING']) {
  test(`reload ${status} resumes polling; unmount stops its scheduled timer`, async () => {
    const p = setup({ getConversation: async () => ({ data: { id: 10, messages: [] } }),
      getAgentExecutions: async () => ({ data: [report({ status, can_resume: false })] }) })
    await p.reloadCurrentConversation()
    await flushPageTasks()
    assert.equal(p.timerCount(), 1)
    p.unmount()
    assert.equal(p.timerCount(), 0)
  })
}

test('switching conversations does not retain an active execution timer', async () => {
  const p = setup({ getConversation: async id => ({ data: { id, messages: [] } }),
    getAgentExecutions: async id => ({ data: id === 10 ? [report({ status: 'RUNNING', can_resume: false })] : [] }) })
  await p.reloadCurrentConversation(); await flushPageTasks()
  assert.equal(p.timerCount(), 1)
  await p.selectConversation(11)
  assert.equal(p.currentConversationId.value, 11)
  assert.equal(p.timerCount(), 0)
  assert.equal(p.executions.value.length, 0)
})

test('historical active-looking records do not poll forever after the current task completed', async () => {
  const p = setup({ getConversation: async () => ({ data: { id: 10, messages: [] } }),
    getAgentExecutions: async () => ({ data: [report({ execution_id: 'latest', status: 'COMPLETED' }),
      report({ status: 'RUNNING', can_resume: true })] }) })
  await p.reloadCurrentConversation(); await flushPageTasks()
  assert.equal(p.timerCount(), 0)
  assert.equal(p.sendBlocked.value, false)
})
const action = { id: 3, status: 'PENDING', risk_level: 'HIGH', summary: '取消受控草稿' }

test('approval locks before opening dialog and prevents duplicate confirmation', async () => {
  let resolve, writes = 0
  const p = setup({ confirmPendingAction: async () => writes++, getConversation: async () => ({ data: { id: 10 } }) }, 'ADMIN', () => new Promise(r => { resolve = r }))
  const first = p.handleConfirmAction(action)
  assert.equal(p.interactionLocked.value, true)
  await p.handleConfirmAction(action)
  await p.selectConversation(11)
  assert.equal(p.currentConversationId.value, 10)
  resolve(true); await first
  assert.equal(writes, 1)
  assert.equal(p.actionLoadingId.value, null)
})

test('cancelled confirmation dialog does not call write API', async () => {
  const p = setup({ confirmPendingAction: () => assert.fail('write') }, 'ADMIN', async () => { throw 'cancel' })
  await p.handleConfirmAction(action)
  assert.equal(p.actionLoadingId.value, null)
})

for (const status of [403, 409, 500, 0]) {
  test(`approval error ${status} reads authoritative state without replay`, async () => {
    let writes = 0, reads = 0
    const p = setup({ confirmPendingAction: async () => { writes++; throw { status } }, getConversation: async () => { reads++; return { data: { id: 10, pending_actions: [{ ...action, status: 'EXPIRED' }] } } } })
    await p.handleConfirmAction(action)
    assert.equal(writes, 1); assert.equal(reads, 1)
    assert.equal(p.currentConversation.value.pending_actions[0].status, 'EXPIRED')
    assert.equal(p.actionLoadingId.value, null)
  })
}

test('failed read after approval network error preserves history and unlocks', async () => {
  const p = setup({ confirmPendingAction: async () => { throw { status: 0 } }, getConversation: async () => { throw { status: 0 } } })
  await p.handleConfirmAction(action)
  assert.equal(p.currentConversation.value.messages[0].content, '已有历史')
  assert.equal(p.actionLoadingId.value, null)
})

test('viewer and terminal action handlers cannot submit confirmation or rejection', async () => {
  const api = { confirmPendingAction: () => assert.fail('write'), cancelPendingAction: () => assert.fail('write') }
  const viewer = setup(api, 'VIEWER')
  await viewer.handleConfirmAction(action); await viewer.handleCancelAction(action)
  for (const status of ['EXECUTED', 'CANCELLED', 'EXPIRED', 'FAILED']) {
    const admin = setup(api)
    await admin.handleConfirmAction({ ...action, status }); await admin.handleCancelAction({ ...action, status })
  }
})

test('rejection conflict refreshes state without retrying write', async () => {
  let writes = 0
  const p = setup({ cancelPendingAction: async () => { writes++; throw { status: 409 } }, getConversation: async () => ({ data: { id: 10, pending_actions: [{ status: 'EXECUTED' }] } }) })
  await p.handleCancelAction(action)
  assert.equal(writes, 1); assert.equal(p.currentConversation.value.pending_actions[0].status, 'EXECUTED')
})

for (const status of [0, 500, 'timeout']) {
  test(`send failure ${status} ends loading and preserves input/history; retry succeeds`, async () => {
    let failed = true, sends = 0
    const p = setup({ sendConversationMessage: async () => { sends++; if (failed) throw { status } },
      getConversation: async () => ({ data: { id: 10, messages: [{ content: '新回答' }] } }), listConversations: async () => ({ data: [] }) })
    p.input.value = '只读查询'
    await p.sendMessage()
    assert.equal(p.sending.value, false); assert.equal(p.input.value, '只读查询')
    assert.equal(p.currentConversation.value.messages[0].content, '已有历史')
    assert.equal(sends, 1)
    failed = false; await p.sendMessage()
    assert.equal(sends, 2); assert.equal(p.input.value, '')
  })
}
