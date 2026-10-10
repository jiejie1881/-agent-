const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const test = require('node:test')

function setup() {
  let version = 1
  const calls = { uploads: [], downloads: [] }
  const auth = { ensureLogin: () => version === 1, getToken: () => 'test-token', getSessionVersion: () => version,
    clearSession: () => { version++ }, redirectToLogin: () => {} }
  const context = { module: { exports: {} }, require(name) {
    if (name.endsWith('/auth')) return auth
    if (name.endsWith('/config')) return { API_BASE_URL: 'https://test.invalid/api/driver', SERVER_BASE_URL: 'https://test.invalid' }
    return () => {}
  }, wx: { uploadFile: options => calls.uploads.push(options), downloadFile: options => calls.downloads.push(options) } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../services/task.js'), 'utf8'), context)
  return { service: context.module.exports, calls, auth }
}
const proof = { id: 1, url: '/uploads/delivery-proofs/' + 'a'.repeat(32) + '.png' }

test('authenticated download uses JWT and produces a local preview file', async () => {
  const { service, calls } = setup()
  const promise = service.downloadProof(proof)
  assert.equal(calls.downloads[0].header.Authorization, 'Bearer test-token')
  calls.downloads[0].success({ statusCode: 200, tempFilePath: 'wxfile://photo' })
  assert.equal(await promise, 'wxfile://photo')
})
test('download will not leak token to arbitrary URLs', async () => {
  const { service, calls } = setup()
  await assert.rejects(service.downloadProof({ ...proof, url: 'https://other.invalid/image' }), /地址无效/)
  assert.equal(calls.downloads.length, 0)
})
test('late download after logout cannot restore an old photo', async () => {
  const { service, calls, auth } = setup()
  const promise = service.downloadProof(proof)
  auth.clearSession()
  calls.downloads[0].success({ statusCode: 200, tempFilePath: 'old' })
  await assert.rejects(promise, /状态已变化/)
})
test('replacement upload sends the rejected proof id with JWT', async () => {
  const { service, calls } = setup()
  const promise = service.uploadProof(10, 20, 'local-image', 5)
  assert.equal(calls.uploads[0].formData.replaces_proof_id, '5')
  assert.equal(calls.uploads[0].header.Authorization, 'Bearer test-token')
  calls.uploads[0].success({ statusCode: 200, data: '{"id":6}' })
  assert.equal((await promise).id, 6)
})
test('hydration preserves rejected originals, reason and image failures', async () => {
  const { service, calls } = setup()
  const promise = service.hydrateProofs({ proofs: [{ ...proof, review_status: 'REJECTED', reviews: [{ reason: '模糊' }] }, { ...proof, id: 2, replaces_proof_id: 1, review_status: 'PENDING' }] })
  calls.downloads[0].success({ statusCode: 200, tempFilePath: 'original' })
  calls.downloads[1].fail()
  const stop = await promise
  assert.equal(stop.proofs[0].historical, true)
  assert.equal(stop.proofs[0].review_reason, '模糊')
  assert.match(stop.proofs[1].image_error, /网络/)
})

function signPage(service) {
  let definition
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/sign/index.js'), 'utf8'), {
    require(name) { return name.endsWith('/auth') ? { ensureLogin: () => true, getSessionVersion: () => 1 } : service },
    Page(value) { definition = value }, wx: { showToast() {}, navigateBack() {} }, setTimeout() {}
  })
  return { ...definition, data: { ...definition.data, taskId: 1, stopId: 2, receiverName: '张三' }, setData(value) { Object.assign(this.data, value) } }
}
test('partial upload failure keeps only unfinished files and reloads uploaded proofs', async () => {
  const calls = []
  const page = signPage({ uploadProof: async (_task, _stop, file) => { calls.push(file); if (file === 'second') throw new Error('网络中断') },
    signStop: () => assert.fail('cannot sign before upload succeeds'),
    getStop: async () => ({ proofs: [{ id: 1 }] }), hydrateProofs: async stop => stop })
  page.data.media = ['first', 'second']
  await page.submit()
  assert.deepEqual(calls, ['first', 'second']); assert.equal(page.data.media.length, 1); assert.equal(page.data.media[0], 'second')
  assert.equal(page.data.activeProofCount, 1); assert.equal(page.data.submitting, false); assert.equal(page.data.error, '网络中断')
})
test('replacement page uploads rejected photo without repeating signature', async () => {
  const calls = []
  const page = signPage({ uploadProof: async (...args) => calls.push(args), signStop: () => assert.fail('must not change signature') })
  page.data.replacesProofId = 99; page.data.receiverName = ''; page.data.media = ['replacement']
  await page.submit()
  assert.deepEqual(calls[0], [1, 2, 'replacement', 99]); assert.equal(page.data.error, '')
})
