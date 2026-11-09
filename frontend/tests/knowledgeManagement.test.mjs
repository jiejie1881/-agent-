import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import {computed, ref} from 'vue'
import test from 'node:test'

const base = {id: 1, name: 'synthetic', revision: 0, active_index_id: null, status: 'ACTIVE', read_roles: []}
const index = {id: 2, base_id: 1, status: 'VALIDATED', version: 'synthetic', configuration: {}}
function page(overrides = {}, role = 'ADMIN', confirm = async () => true) {
  const source = readFileSync(new URL('../src/views/knowledge/KnowledgeManagementView.vue', import.meta.url), 'utf8').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const compiled = ts.transpileModule(source + '\nexport {bases,baseId,indexId,indexes,file,upload,busy,error,createBuild,pendingBuildKey,publish,query,search,result,candidatePreview,refresh,chooseBase,chooseIndex,chunks,chunkOffset,chunkTotal,chunkCharacters,versions,evaluationId,jobId,runBuild,success,newBase,creatingBase,name}',
    {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText
  const api = {listBases: async () => ({data: [base]}), listDocuments: async () => ({data: []}),
    listJobs: async () => ({data: []}), listIndexes: async () => ({data: [index]}), listEvaluations: async () => ({data: []}),
    knowledgeMetrics: async () => ({data: {actual_cost: null}}), knowledgeAudits: async () => ({data: []}),
    indexDiff: async () => ({data: {added_documents: ['1'], removed_documents: [], updated_documents: []}}), ...overrides}
  const module = {exports: {}}
  const deps = {vue: {computed, ref, onMounted() {}}, 'element-plus': {ElMessageBox: {confirm}},
    '@/stores/auth': {useAuthStore: () => ({user: {role}})}, '@/api/knowledge': api}
  let ids = 0
  vm.runInNewContext(compiled, {module, exports: module.exports, require: name => deps[name],
    crypto: {randomUUID: () => `synthetic-key-${++ids}`}, Object, String, JSON, Promise})
  const p = module.exports
  p.bases.value = [base]; p.baseId.value = 1; p.indexes.value = [index]; p.indexId.value = 2
  return p
}

test('upload rejects excessive files before API and does not permit viewers', async () => {
  let calls = 0
  for (const role of ['ADMIN', 'VIEWER']) {
    const p = page({uploadDocument: async () => calls++}, role)
    p.file.value = {name: 'rules.txt', size: role === 'ADMIN' ? 6 * 1024 * 1024 : 20}
    await p.upload()
  }
  assert.equal(calls, 0)
})

test('uncertain create response retains idempotency key for safe retry', async () => {
  const keys = []; let attempt = 0
  const p = page({createJob: async (_id, key) => { keys.push(key); if (!attempt++) throw new Error('synthetic timeout'); return {data: {id: 3}} }})
  await p.createBuild(); const key = p.pendingBuildKey.value
  assert.ok(key); await p.createBuild()
  assert.deepEqual(keys, [key, key]); assert.equal(p.pendingBuildKey.value, '')
})

test('build creation never publishes an index', async () => {
  let published = 0
  const p = page({createJob: async () => ({data: {id: 3}}), publishIndex: async () => published++})
  await p.createBuild(); assert.equal(published, 0)
})

test('publish cancellation prevents final API mutation', async () => {
  let mutations = 0
  const p = page({publishIndex: async () => mutations++}, 'ADMIN', async () => { throw 'cancel' })
  await p.publish(); assert.equal(mutations, 0); assert.equal(p.busy.value, false)
})

test('CAS conflict is shown and never automatically retried', async () => {
  let attempts = 0
  const p = page({publishIndex: async () => { attempts++; throw new Error('活动索引已变化') }})
  await p.publish(); assert.equal(attempts, 1); assert.match(p.error.value, /已变化/)
})

test('candidate preview requires selection and empty evidence remains a refusal state', async () => {
  let calls = 0
  const p = page({laboratory: async () => { calls++; return {data: {results: [], candidates: [], evidence_status: 'NO_EVIDENCE', generation: 'NOT RUN'}} }})
  p.query.value = 'anonymous'; p.candidatePreview.value = true; p.indexId.value = undefined
  await p.search(); assert.equal(calls, 0)
  p.candidatePreview.value = false; await p.search(); assert.equal(calls, 1)
  assert.equal(p.result.value.evidence_status, 'NO_EVIDENCE'); assert.equal(p.result.value.generation, 'NOT RUN')
})

test('all governance panels use escaped text and keep offline/model boundaries explicit', () => {
  const source = readFileSync(new URL('../src/views/knowledge/KnowledgeManagementView.vue', import.meta.url), 'utf8')
  for (const label of ['知识库管理', '文档管理', 'Chunk预览', '索引管理', '检索实验室', '评测中心', '运行监控', '审计管理']) assert.ok(source.includes(label))
  assert.doesNotMatch(source, /v-html|innerHTML/); assert.match(source, /UNKNOWN不代表0/)
  const routes = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')
  assert.match(routes, /system\/knowledge[^\n]+requiresAdmin: true/)
})

test('base switch clears all stale document/chunk/job/evaluation state', () => {
  const p = page()
  p.chunks.value = [{chunk_id: 'old-base', content: 'old'}]; p.chunkOffset.value = 50; p.chunkTotal.value = 99
  p.chunkCharacters.value = 123; p.versions.value = [{id: 9}]; p.evaluationId.value = 9; p.jobId.value = 8
  p.chooseBase()
  assert.equal(p.chunks.value.length, 0); assert.equal(p.chunkOffset.value, 0); assert.equal(p.chunkTotal.value, null)
  assert.equal(p.chunkCharacters.value, 0); assert.equal(p.versions.value.length, 0)
  assert.equal(p.evaluationId.value, undefined); assert.equal(p.jobId.value, undefined)
})

test('refresh loads each endpoint once instead of running load twice', async () => {
  let calls = 0
  const p = page({listBases: async () => { calls++; return {data: [base]} }})
  await p.refresh(); assert.equal(calls, 1)
})

test('publication pins the confirmed index and CAS snapshot', async () => {
  let p, actual
  p = page({publishIndex: async (...args) => { actual = args }}, 'ADMIN', async () => {
    p.indexId.value = 999; p.baseId.value = 999
  })
  await p.publish()
  assert.equal(actual[0], 2); assert.equal(actual[1].id, 1); assert.equal(actual[1].revision, 0)
})

test('failed build shows safe server failure and never a success alert', async () => {
  const p = page({runJob: async () => ({data: {status: 'FAILED', failure_message: '安全失败：请核对存储'}})})
  await p.runBuild({id: 7})
  assert.match(p.error.value, /请核对存储/); assert.equal(p.success.value, ''); assert.equal(p.busy.value, false)
})

test('new-base draft survives refresh instead of reverting to an existing base', async () => {
  const p = page(); p.newBase(); p.name.value = 'new draft'
  await p.refresh()
  assert.equal(p.creatingBase.value, true); assert.equal(p.baseId.value, undefined); assert.equal(p.name.value, 'new draft')
})

test('switching index resets the chunk page and count', () => {
  const p = page(); p.chunkTotal.value = 80; p.chunkOffset.value = 50; p.chunks.value = [{chunk_id: 'old'}]
  p.chooseIndex(); assert.equal(p.chunkTotal.value, null); assert.equal(p.chunkOffset.value, 0); assert.equal(p.chunks.value.length, 0)
})
