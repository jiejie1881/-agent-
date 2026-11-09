const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

for (const action of ['start', 'arrive']) {
  test('uncertain ' + action + ' response reloads authoritative task without resubmitting', async () => {
    let pageDefinition, writes = 0, reads = 0
    const service = {
      async startTask() { writes++; throw new Error('网络超时，请核对任务状态') },
      async arriveStop() { writes++; throw new Error('网络超时，请核对任务状态') },
      async getTask() { reads++; return { status: 'DELIVERING', stops: [{ delivery_status: 'ARRIVED', proofs: [] }] } },
      async hydrateProofs(stop) { return stop }
    }
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/task-detail/index.js'), 'utf8'), {
      require(name) { return name.includes('/task') ? service : { getSessionVersion: () => 1 } },
      Page(value) { pageDefinition = value },
      wx: { showModal(options) { options.success({ confirm: true }) }, showToast() { assert.fail('uncertain write must not show success') } }
    })
    const page = { ...pageDefinition, data: { ...pageDefinition.data, taskId: 9 }, setData(value) { Object.assign(this.data, value) } }
    if (action === 'start') await page.perform({ currentTarget: { dataset: { action } } })
    else await page.arrive({ currentTarget: { dataset: { stopId: 7 } } })
    assert.equal(writes, 1)
    assert.equal(reads, 1)
    assert.equal(page.data.task.status, 'DELIVERING')
    assert.equal(page.data.task.stops[0].delivery_status, 'ARRIVED')
    assert.equal(page.data.operating, false)
    assert.match(page.data.error, /核对任务状态/)
  })
}

test('failed reload after account change clears previously visible task and completion permission', async () => {
  let definition
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/task-detail/index.js'), 'utf8'), {
    require(name) { return name.includes('/task') ? { async getTask() { throw new Error('拒绝读取此任务') } } : { getSessionVersion: () => 2 } },
    Page(value) { definition = value }
  })
  const page = { ...definition, data: { ...definition.data, taskId: 9, task: { status: 'COMPLETED' }, canComplete: true }, setData(value) { Object.assign(this.data, value) } }
  await page.load()
  assert.equal(page.data.task, null)
  assert.equal(page.data.canComplete, false)
  assert.match(page.data.error, /拒绝/)
})
