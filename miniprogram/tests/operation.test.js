const assert = require('node:assert/strict')
const test = require('node:test')
const operations = require('../utils/operation')

function platform() {
  const storage = new Map([['driver_user', { id: 11 }]])
  return { storage, getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, JSON.parse(JSON.stringify(value))) }
}
test('lost response reuses persisted key even after module/page reload', () => {
  const wx = platform()
  const a = operations.begin(wx, 'upload', 1, 2, { filePath: 'same-local-file' })
  delete require.cache[require.resolve('../utils/operation')]
  const b = require('../utils/operation').begin(wx, 'upload', 1, 2, { filePath: 'same-local-file' })
  assert.equal(a.key, b.key)
  assert.match(a.key, /^[a-f0-9]{32}$/)
  operations.complete(wx, b)
  assert.notEqual(operations.begin(wx, 'upload', 1, 2, { filePath: 'same-local-file' }).key, a.key)
})
test('different driver or changed payload never inherits a pending key', () => {
  const wx = platform()
  const a = operations.begin(wx, 'sign', 1, 2, { receiver_name: 'isolated' })
  assert.notEqual(operations.begin(wx, 'sign', 1, 2, { receiver_name: 'changed' }).key, a.key)
  wx.storage.set('driver_user', { id: 12 })
  assert.notEqual(operations.begin(wx, 'sign', 1, 2, { receiver_name: 'isolated' }).key, a.key)
})
test('storage failure blocks an unprotected write', () => {
  const wx = platform()
  wx.setStorageSync = () => { throw new Error('quota') }
  assert.throws(() => operations.begin(wx, 'upload', 1, 2, {}), /无法保存重试凭据/)
})
