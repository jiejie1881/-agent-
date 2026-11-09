import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { ref } from 'vue'

function setup(api = {}, role = 'ADMIN', dialogs = {}) {
  const script = readFileSync(new URL('../src/views/dispatch/components/DeliveryReceiptPanel.vue', import.meta.url), 'utf8').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const source = ts.transpileModule(script + '\nexport { loadImages, images, errors, loading, review, pending, isHistorical }', { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const module = { exports: {} }, revoked = [], messages = []
  const proof = { id: 1, review_status: 'PENDING', reviews: [] }
  const props = { stops: [{ proofs: [proof] }] }
  const dependencies = { vue: { ref, watch() {}, onBeforeUnmount() {} }, '@/api/delivery-proofs': api,
    '@/stores/auth': { useAuthStore: () => ({ user: { role }, isAuthenticated: true }) },
    'element-plus': { ElMessage: { success() {}, error: message => messages.push(message) }, ElMessageBox: { confirm: async () => true, prompt: async () => ({ value: '照片模糊' }), ...dialogs } } }
  vm.runInNewContext(source, { module, exports: module.exports, require: name => dependencies[name], defineProps: () => props, defineEmits: () => () => {}, URL: { revokeObjectURL: url => revoked.push(url) } })
  return { ...module.exports, proof, props, revoked, messages }
}
test('receipt photos use authenticated API, keep per-image errors and release old blobs', async () => {
  let fail = false
  const p = setup({ loadProofImage: async () => { if (fail) throw { message: '图片不可用' }; return 'blob:test' } })
  await p.loadImages(); assert.equal(p.images.value[1], 'blob:test'); assert.equal(p.loading.value, false)
  fail = true; await p.loadImages(); assert.equal(p.revoked[0], 'blob:test'); assert.equal(p.errors.value[1], '图片不可用'); assert.equal(p.loading.value, false)
})
test('outdated image requests cannot overwrite current results', async () => {
  let resolve, count = 0
  const p = setup({ loadProofImage: () => ++count === 1 ? new Promise(r => { resolve = r }) : Promise.resolve('blob:new') })
  const first = p.loadImages(); await p.loadImages(); resolve('blob:old'); await first
  assert.equal(p.images.value[1], 'blob:new'); assert.equal(p.revoked.includes('blob:old'), true)
})
test('non-admin cannot trigger receipt review', async () => {
  for (const role of ['DISPATCHER', 'VIEWER']) {
    const p = setup({ reviewProof: () => assert.fail('not admin') }, role)
    await p.review(p.proof, 'APPROVED')
  }
})
test('cancelling review does not call backend', async () => {
  const p = setup({ reviewProof: () => assert.fail('cancelled') }, 'ADMIN', { confirm: async () => { throw 'cancel' } })
  await p.review(p.proof, 'APPROVED'); assert.equal(p.pending.value, null)
})
test('reject sends reason and preserves review history returned by backend', async () => {
  const calls = []
  const p = setup({ reviewProof: async (...args) => { calls.push(args); return { data: { review_status: 'REJECTED', reviews: [{ id: 1, reason: '照片模糊' }] } } } })
  await p.review(p.proof, 'REJECTED')
  assert.deepEqual(calls[0], [1, 'REJECTED', '照片模糊']); assert.equal(p.proof.reviews[0].reason, '照片模糊')
})
test('review failure releases submit lock and displays business error', async () => {
  const p = setup({ reviewProof: async () => { throw { message: '已被审核' } } })
  await p.review(p.proof, 'APPROVED'); assert.equal(p.pending.value, null); assert.equal(p.messages[0], '已被审核')
})
