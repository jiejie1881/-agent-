import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { computed, ref } from 'vue'

function page(api) {
  const source = readFileSync(new URL('../src/views/drivers/DriverSchedulingView.vue', import.meta.url), 'utf8').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const compiled = ts.transpileModule(source + '\nexport { load, error, loading, errorMessage, openAttendance, attendanceEdit, save, dialog, day }', { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const module = { exports: {} }
  const dependencies = {
    vue: { computed, ref, onMounted: () => {} },
    'element-plus': { ElMessage: { success: () => {} } },
    '@/stores/auth': { useAuthStore: () => ({ user: { role: 'DISPATCHER' } }) },
    '@/api/driverScheduling': api,
  }
  vm.runInNewContext(compiled, { module, exports: module.exports, require: name => dependencies[name], Date, Map, Promise })
  return module.exports
}

test('plain ApiError displays its actual message and ends loading', async () => {
  const p = page({ fetchDrivers: async () => { throw { status: 500, message: '真实接口错误' } }, fetchShifts: async () => ({ data: [] }), fetchLeaves: async () => ({ data: [] }) })
  await p.load()
  assert.equal(p.error.value, '真实接口错误')
  assert.equal(p.loading.value, false)
})

test('unknown errors have a fallback; retry clears the error', async () => {
  let failed = true
  const p = page({ fetchDrivers: async () => { if (failed) throw null; return { data: [] } }, fetchShifts: async () => ({ data: [] }), fetchLeaves: async () => ({ data: [] }) })
  await p.load()
  assert.equal(p.error.value, '加载失败')
  assert.equal(p.loading.value, false)
  failed = false
  await p.load()
  assert.equal(p.error.value, '')
})

test('attendance opens a scope dialog without immediately changing data', () => {
  let calls = 0
  const p = page({ setDriverAttendance: () => calls++ })
  p.day.value = '2026-10-09'
  p.openAttendance({ id: 15, username: 'driver01' }, 'MORNING', true)
  assert.equal(p.dialog.value, 'attendance')
  assert.equal(p.attendanceEdit.value.scope, 'ONCE')
  assert.equal(p.attendanceEdit.value.date, '2026-10-09')
  assert.equal(calls, 0)
})

for (const scope of ['ONCE', 'PERMANENT']) {
  test(`${scope} uses the corresponding authenticated API and captured date`, async () => {
    const calls = []
    const p = page({
      fetchDrivers: async () => ({ data: [] }), fetchShifts: async () => ({ data: [] }), fetchLeaves: async () => ({ data: [] }),
      setDriverAttendance: async (...args) => calls.push(['ONCE', ...args]),
      setFixedDriverAttendance: async (...args) => calls.push(['PERMANENT', ...args]),
    })
    p.day.value = '2026-10-09'
    p.openAttendance({ id: 15, username: 'driver01' }, 'AFTERNOON', false)
    p.attendanceEdit.value.scope = scope
    p.day.value = '2026-10-10'
    p.save()
    await new Promise(resolve => setImmediate(resolve))
    assert.deepEqual(calls, [[scope, 15, '2026-10-09', 'AFTERNOON', false]])
  })
}
