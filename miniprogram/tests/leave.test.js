const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
function page(service, loggedIn = true) {
  let definition
  const wx = { showToast() {}, showModal(value) { wx.modal = value } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/leave/index.js'), 'utf8'), { Page(value) { definition = value }, require: name => name.endsWith('/auth') ? { ensureLogin: () => loggedIn } : service, wx })
  return { p: { ...definition, data: { ...definition.data }, setData(value) { Object.assign(this.data, value) } }, wx }
}
test('leave load errors render feedback and retry ends loading', async () => {
  let failed = true
  const { p } = page({ list: async () => { if (failed) throw Error('网络失败'); return [{ id: 1, status: 'PENDING', period: 'ALL_DAY' }] } })
  await p.load(); assert.equal(p.data.error, '网络失败'); assert.equal(p.data.loading, false)
  failed = false; await p.load(); assert.equal(p.data.records[0].statusLabel, '待审批')
})
test('submit uses authenticated own API without driver_id', async () => {
  const calls = []
  const { p } = page({ submit: async data => calls.push(data), list: async () => [] })
  Object.assign(p.data, { start_date: '2026-10-09', end_date: '2026-10-10', leave_type: '事假', reason: '个人事务' })
  await p.submit(); assert.equal(calls.length, 1); assert.equal('driver_id' in calls[0], false); assert.equal(calls[0].period, 'ALL_DAY'); assert.equal(p.data.saving, false)
})
test('invalid range never submits', async () => {
  const { p } = page({ submit: async () => assert.fail('invalid data must not submit') })
  Object.assign(p.data, { start_date: '2026-10-10', end_date: '2026-10-09', leave_type: '事假', reason: '事项' }); await p.submit()
})
test('withdraw requires user confirmation', async () => {
  let calls = 0
  const { p, wx } = page({ withdraw: async () => calls++, list: async () => [] })
  p.withdraw({ currentTarget: { dataset: { id: 1 } } }); await wx.modal.success({ confirm: false }); assert.equal(calls, 0)
  p.withdraw({ currentTarget: { dataset: { id: 1 } } }); await wx.modal.success({ confirm: true }); assert.equal(calls, 1)
})
test('unauthenticated leave page makes no request', async () => {
  const { p } = page({ list: async () => assert.fail('no auth'), submit: async () => assert.fail('no auth') }, false)
  await p.load(); await p.submit()
})
