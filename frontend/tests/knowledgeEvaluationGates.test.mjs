import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'
import * as Vue from 'vue'
import {parse, compileScript} from '@vue/compiler-sfc'
import {renderToString} from '@vue/server-renderer'

const source = readFileSync(new URL('../src/components/knowledge/KnowledgeEvaluationGates.vue', import.meta.url), 'utf8')
const script = compileScript(parse(source).descriptor, {id: 'knowledge-gates', inlineTemplate: true}).content
const compiled = ts.transpileModule(script, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText
async function render(metrics, status = 'PASS') {
  const module = {exports: {}}
  vm.runInNewContext(compiled, {module, exports: module.exports, require: () => Vue})
  return renderToString(Vue.createSSRApp(module.exports.default, {evaluation: {status, metrics}}))
}

test('retrieval PASS does not hide refusal failure or overall partial', async () => {
  const html = await render({acceptance_gates: {retrieval: 'PASS', retrieval_abstention: 'FAIL', overall: 'PARTIAL'}})
  assert.match(html, /历史指标状态：PASS/)
  assert.match(html, /无答案拒答<\/th><td>FAIL/)
  assert.match(html, /整体准入<\/th><td>PARTIAL/)
  assert.match(html, /证据充分性<\/th><td>NOT VERIFIED/)
})

test('legacy smoke PASS and absent gate data never synthesize overall PASS', async () => {
  const html = await render({scope: 'OFFLINE_SYNTHETIC_DOCUMENT_SMOKE_NOT_BLIND'})
  assert.match(html, /整体准入<\/th><td>NOT VERIFIED/)
  assert.match(html, /不能证明真实模型效果/)
})

test('invalid gate values and arrays remain unverified', async () => {
  for (const gates of [[], {overall: true}, {overall: 'READY'}, {overall: '<script>'}]) {
    assert.match(await render({acceptance_gates: gates}), /整体准入<\/th><td>NOT VERIFIED/)
  }
})

test('explicit backend blocked states are preserved without mutating record', async () => {
  const metrics = Object.freeze({acceptance_gates: Object.freeze({retrieval: 'PASS', final_generation: 'BLOCKED', overall: 'PARTIAL'})})
  assert.match(await render(metrics), /最终回答<\/th><td>BLOCKED/)
  assert.equal(metrics.acceptance_gates.overall, 'PARTIAL')
})
