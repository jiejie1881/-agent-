import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'
import * as Vue from 'vue'
import {parse, compileScript} from '@vue/compiler-sfc'
import {renderToString} from '@vue/server-renderer'

function compile(source) {
  const module = {exports: {}}
  const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText
  return {module, compiled}
}
const util = compile(readFileSync(new URL('../src/utils/knowledgeEvaluation.ts', import.meta.url), 'utf8'))
vm.runInNewContext(util.compiled, {module: util.module, exports: util.module.exports})

async function render(runs = [], selected) {
  const source = readFileSync(new URL('../src/components/knowledge/KnowledgeEvaluationAnalysis.vue', import.meta.url), 'utf8')
  const {module, compiled} = compile(compileScript(parse(source).descriptor, {id: 'analysis', inlineTemplate: true}).content)
  vm.runInNewContext(compiled, {module, exports: module.exports, require: name => name === 'vue' ? Vue : util.module.exports})
  const app = Vue.createSSRApp(module.exports.default, {runs, indexes: [], selected})
  app.component('el-drawer', {props: ['modelValue'], setup: (props, {slots}) => () => props.modelValue ? Vue.h('div', slots.default?.()) : null})
  return renderToString(app)
}
const run = (id, strategy, overrides = {}) => ({
  id, index_id: 1, dataset: 'fixed', dataset_sha256: 'fixed-hash', status: 'PASS',
  metrics: {strategy, scope: 'OFFLINE_FIXTURE', k: 4, queries: 1, recall_at_k: .5, precision_at_k: 0, mrr: .3, ndcg: .4,
    pipeline: {answer_quality: {status: 'NOT RUN'}, usage: {cost: {value: null}}}},
  cases: [{id: 'x', query: '<script>unsafe</script>', expected: ['gold'], returned: ['gold'], status: 'COMPLETED'}],
  ...overrides,
})

test('empty and blocked histories render without fabricated measurements', async () => {
  assert.match(await render(), /还没有评测记录/)
  const html = await render([run(1, 'bm25', {status: 'BLOCKED', cases: []})])
  assert.match(html, /已阻塞/)
  assert.doesNotMatch(html, /<progress|50\.00%/)
})

test('executed measures include real zeros and suppress unmeasured families', async () => {
  const html = await render([run(1, 'bm25'), run(2, 'hybrid')])
  assert.equal((html.match(/<progress/g) ?? []).length, 8)
  assert.match(html, /0\.00%/)
  assert.match(html, /最高 nDCG/)
  assert.doesNotMatch(html, /NOT RUN|回答质量|Token与成本/)
})

test('comparison separates index, dataset digest, K and scope', async () => {
  for (const overrides of [{index_id: 2}, {dataset_sha256: 'other'}, {metrics: {...run(2, 'hybrid').metrics, k: 5}},
    {metrics: {...run(2, 'hybrid').metrics, scope: 'REAL'}}]) {
    const html = await render([run(1, 'bm25'), run(2, 'hybrid', overrides)])
    assert.equal((html.match(/<progress/g) ?? []).length, 4)
    assert.doesNotMatch(html, /最高 nDCG/)
  }
})

test('completed legacy smoke runs render without fabricated strategy or questions', async () => {
  const legacy = run(1, 'bm25', {dataset: 'document_smoke', cases: [{id: 'chunk', expected: ['chunk'], returned: ['chunk']}]})
  delete legacy.metrics.strategy
  const html = await render([legacy], 1)
  assert.match(html, /BM25/)
  assert.match(html, /检索样本 1/)
  assert.match(html, /命中 Gold/)
})

test('untrusted question is escaped and the original execution record remains inspectable', async () => {
  const html = await render([run(1, 'bm25')], 1)
  assert.doesNotMatch(html, /<script>unsafe/)
  assert.match(html, /&lt;script&gt;/)
  assert.match(html, /单题原始执行证据/)
})

test('document and current-page chunk filters operate on API state and reset on base switch', () => {
  const source = readFileSync(new URL('../src/views/knowledge/KnowledgeManagementView.vue', import.meta.url), 'utf8').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const {module, compiled} = compile(source + '\nexport {documents,chunks,documentSearch,documentState,chunkSearch,filteredDocuments,filteredChunks,chooseBase}')
  const deps = {vue: {...Vue, onMounted() {}}, 'element-plus': {}, '@/stores/auth': {useAuthStore: () => ({user: {role: 'ADMIN'}})}}
  vm.runInNewContext(compiled, {module, exports: module.exports, require: key => deps[key]})
  const p = module.exports
  p.documents.value = [{title: 'Truck规则', deleted: false}, {title: 'OLD规则', deleted: true}]
  p.documentSearch.value = 'TRUCK'; assert.equal(p.filteredDocuments.value.length, 1)
  p.documentSearch.value = ''; p.documentState.value = 'deleted'; assert.equal(p.filteredDocuments.value[0].title, 'OLD规则')
  p.chunks.value = [{content: '载重一吨'}, {content: '出勤'}]; p.chunkSearch.value = '载重'
  assert.equal(p.filteredChunks.value.length, 1)
  p.chooseBase(); assert.equal(p.chunkSearch.value, ''); assert.equal(p.documentState.value, 'all')
})

test('cross-version quality requires matching Gold, dataset provenance and complete runs', () => {
  const {evaluationEntry, comparableProtocol} = util.module.exports
  const before = run(1, 'bm25')
  before.metrics.pipeline.provenance = {dataset_sha256: 'fixed-hash', corpus_version: 'corpus', k: 4}
  const after = structuredClone(before)
  after.index_id = 2
  const protocol = row => comparableProtocol(evaluationEntry(row))
  assert.ok(protocol(before))
  assert.equal(protocol(before), protocol(after))
  after.cases[0].expected = ['another-gold']
  assert.notEqual(protocol(before), protocol(after))
  after.cases[0].status = 'ERROR'
  assert.equal(protocol(after), null)
  delete before.metrics.pipeline.provenance.corpus_version
  assert.equal(protocol(before), null)
})

test('version comparison renders document changes and paired Gold regressions', async () => {
  const source = readFileSync(new URL('../src/components/knowledge/KnowledgeVersionCompare.vue', import.meta.url), 'utf8')
  const {module, compiled} = compile(compileScript(parse(source).descriptor, {id: 'version-compare', inlineTemplate: true}).content)
  vm.runInNewContext(compiled, {module, exports: module.exports, require: name => name === 'vue' ? Vue : util.module.exports})
  const index = (id, snapshot) => ({id, snapshot, status: 'VALIDATED', version: 'index-' + id,
    embedding_model: 'fixture', model_revision: 'r1', dimension: 192, configuration: {chunk: {size: 200}}})
  const before = run(1, 'bm25')
  before.metrics.pipeline.provenance = {dataset_sha256: 'fixed-hash', corpus_version: 'corpus', k: 4}
  const after = structuredClone(before)
  after.id = 2
  after.index_id = 2
  after.cases[0].returned = []
  const props = {indexes: [index(1, {'5': 7}), index(2, {'5': 7})],
    documents: [{id: 5, title: '调度规则'}], runs: [before, after]}
  let html = await renderToString(Vue.createSSRApp(module.exports.default, props))
  assert.match(html, /新增完全漏召回/)
  assert.match(html, /目标批次 #2/)
  props.indexes[1].snapshot = {'5': 8}
  after.metrics.pipeline.provenance.corpus_version = 'updated'
  html = await renderToString(Vue.createSSRApp(module.exports.default, props))
  assert.match(html, /调度规则/)
  assert.match(html, /版本更新/)
  assert.doesNotMatch(html, /差值（百分点）/)
})
