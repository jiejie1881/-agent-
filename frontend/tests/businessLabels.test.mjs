import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const source = readFileSync(new URL('../src/utils/businessLabels.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const module = { exports: {} }
vm.runInNewContext(compiled, { module, exports: module.exports })
const { businessRef, planRef, typeLabel } = module.exports

test('business references preserve actual key and date, including keys above 999', () => {
  assert.equal(businessRef('DRV', 7), 'DRV-007')
  assert.equal(businessRef('DEM', 1024, '2026-11-06'), 'DEM-20261106-1024')
  assert.equal(businessRef('TASK', undefined), '未记录')
  assert.equal(planRef('2026-11-06', 2), 'DP-20261106-V2')
})

test('vehicle display depends on code, never inferred from load', () => {
  assert.equal(typeLabel('FOUR_METER', '自定义名称'), '4.2米厢式货车')
  assert.equal(typeLabel('BIG_VAN'), '大型面包车')
  assert.equal(typeLabel('SMALL_VAN'), '小型面包车')
  assert.equal(typeLabel('UNKNOWN', '配置车型'), '配置车型')
})

test('enterprise report labels use persisted snapshots, not fabricated legacy identities', () => {
  const report = readFileSync(new URL('../src/views/dispatch/DispatchQualityView.vue', import.meta.url), 'utf8')
  assert.match(report, /report\.value\?\.entities\?\.tasks/)
  assert.match(report, /车牌未记录/)
  assert.match(report, /司机未记录/)
  const detail = readFileSync(new URL('../src/views/dispatch/DispatchPlanDetailView.vue', import.meta.url), 'utf8')
  assert.match(detail, /businessRef\('DRV',\s*order\.actual_driver_id\)/)
})
