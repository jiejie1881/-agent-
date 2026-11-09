import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'
import * as Vue from 'vue'
import { parse, compileScript } from '@vue/compiler-sfc'
import { renderToString } from '@vue/server-renderer'

async function render(executions, extraProps = {}) {
  const source = readFileSync(new URL('../src/views/agent/components/AgentExecutionPanel.vue', import.meta.url), 'utf8')
  const script = compileScript(parse(source).descriptor, { id: 'agent-steps', inlineTemplate: true }).content
  const compiled = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const module = { exports: {} }
  vm.runInNewContext(compiled, { module, exports: module.exports, require: () => Vue })
  return renderToString(Vue.createSSRApp(module.exports.default, { executions, ...extraProps }))
}

const execution = {
  execution_id: 'synthetic-execution', intent: 'COMPOSITE', status: 'WAITING_APPROVAL', current_node: 'finish',
  tool_attempts: 3, replans: 1, elapsed_ms: 14,
  plan: [{ id: 's3', tool: 'cancel_dispatch_plan', depends_on: ['s1', 's2'], requires_confirmation: true }],
  events: [{ node: 'tools', step_id: 's1', tool: 'list_drivers', status: 'SUCCEEDED', elapsed_ms: 4, parallel_group: 'group1' }],
}

test('compiled panel renders approval barrier, dependency, tools and parallel group', async () => {
  const html = await render([execution])
  for (const text of ['等待人工确认', '业务操作尚未执行', '依赖 s1、s2', 'list_drivers', '并行组 group1', 'synthetic-execution']) assert.ok(html.includes(text), text)
})
test('compiled panel renders failure and finite replanning without claiming success', async () => {
  const html = await render([{ ...execution, status: 'FAILED', events: [{ node: 'tools', tool: 'list_drivers', status: 'FAILED', elapsed_ms: 2, error_code: 'TIMEOUT' }] }])
  assert.match(html, /执行失败/); assert.match(html, /TIMEOUT/); assert.match(html, /重规划 1 次/)
})
test('empty history renders no invented workflow', async () => {
  assert.ok(!(await render([])).includes('任务执行过程'))
})
test('execution values are escaped rather than interpreted as markup', async () => {
  const html = await render([{ ...execution, execution_id: '<script>attack()</script>' }])
  assert.ok(!html.includes('<script>')); assert.match(html, /&lt;script&gt;/)
})

test('recovery action is available only when the backend explicitly permits it', async () => {
  const allowed = await render([{ ...execution, status: 'FAILED', can_resume: true, recovery_reason: 'READ_ONLY_CHECKPOINT' }])
  assert.match(allowed, /恢复执行/); assert.match(allowed, /READ_ONLY_CHECKPOINT/)
  for (const can_resume of [undefined, false]) {
    const denied = await render([{ ...execution, status: 'FAILED', can_resume }])
    assert.ok(!denied.includes('resume-button'))
  }
})

test('ongoing resume disables further recovery buttons without claiming completion', async () => {
  const html = await render([{ ...execution, can_resume: true, status: 'RECOVERING' }], { resumeLoadingId: execution.execution_id, disabled: true })
  assert.match(html, /恢复执行中/); assert.match(html, /正在恢复…/)
  assert.match(html, /disabled/); assert.ok(!html.includes('已完成'))
})

test('retry attempts, delay and structured error category come from recorded events', async () => {
  const html = await render([{ ...execution, status: 'RETRYING', events: [
    { node: 'tools', tool: 'list_drivers', status: 'RETRYING', error_category: 'DATABASE_TRANSIENT',
      attempt: 1, max_attempts: 2, retry_delay_ms: 100 },
  ] }])
  for (const text of ['等待有限重试', '第 1/2 次尝试', '等待 100 ms', 'DATABASE_TRANSIENT']) assert.ok(html.includes(text), text)
})

test('timeout and manual review remain visible failure-handling states', async () => {
  for (const [status, text] of [['TIMED_OUT', '执行超时'], ['MANUAL_REVIEW', '需要人工处理']]) {
    const html = await render([{ ...execution, status }])
    assert.ok(html.includes(text)); assert.ok(!html.includes('已完成'))
  }
})

test('failed state refresh warns even when no execution report could be loaded', async () => {
  const html = await render([], { statusError: true })
  assert.match(html, /执行状态暂时更新失败/); assert.match(html, /保留上次记录/)
  assert.ok(!html.includes('已完成'))
})

test('recovered final message is displayed from the backend and remains escaped text', async () => {
  const html = await render([{ ...execution, status: 'COMPLETED', final_message: '执行恢复完成\n<script>attack()</script>' }])
  assert.match(html, /执行结果/); assert.match(html, /执行恢复完成/)
  assert.match(html, /&lt;script&gt;attack\(\)&lt;\/script&gt;/)
  assert.ok(!html.includes('<script>'))
})

test('missing final message never invents an execution result', async () => {
  const html = await render([{ ...execution, status: 'FAILED', final_message: null }])
  assert.ok(!html.includes('execution-result'))
})

test('approval card keeps business snapshot details while hiding the internal fingerprint', async () => {
  const source = readFileSync(new URL('../src/views/agent/components/AgentPendingActionCard.vue', import.meta.url), 'utf8')
  const script = compileScript(parse(source).descriptor, { id: 'agent-approval', inlineTemplate: true }).content
  const compiled = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const module = { exports: {} }
  vm.runInNewContext(compiled, { module, exports: module.exports, require: () => Vue })
  const app = Vue.createSSRApp(module.exports.default, { action: {
    id: 3, tool_name: 'cancel_dispatch_plan', summary: '取消受控草稿', risk_level: 'HIGH', status: 'PENDING',
    risk_message: '请核对业务对象', display_data: { plan_id: 42, expected_version: 2, approval_fingerprint: 'internal-hash-must-not-render' },
  }, loading: false, canOperate: true })
  const passthrough = Vue.defineComponent({ setup(_props, { slots }) { return () => Vue.h('div', [slots.header?.(), slots.default?.()]) } })
  for (const name of ['ElCard', 'ElTag', 'ElAlert', 'ElButton']) app.component(name, passthrough)
  const html = await renderToString(app)
  assert.match(html, /plan_id/); assert.match(html, /42/); assert.match(html, /expected_version/)
  assert.match(html, /确认执行/)
  assert.ok(!html.includes('approval_fingerprint')); assert.ok(!html.includes('internal-hash-must-not-render'))
})


test('active execution exposes cancellation request without claiming cleanup', async () => {
 const html = await render([{...execution,status:'RUNNING',can_resume:false}],{cancelPending:true});
 assert.match(html,/请求取消执行/);assert.match(html,/disabled/);assert.ok(!html.includes('已取消'));
});
test('approval and terminal reports never expose task cancellation as approval rejection', async () => {
 for (const status of ['WAITING_APPROVAL','COMPLETED','CANCELLED']) {
  assert.ok(!(await render([{...execution,status}])).includes('请求取消执行'));
 }
});
