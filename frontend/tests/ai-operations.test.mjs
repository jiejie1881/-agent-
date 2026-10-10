import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
function load(file) {
  const source = readFileSync(new URL(`../src/${file}`,import.meta.url),'utf8')
  const compiled = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText
  const module={exports:{}}; vm.runInNewContext(compiled,{module,exports:module.exports,require:()=>({})}); return module.exports
}
const preview=load('views/operations/components/aiDemandPreview.ts'), quality=load('views/dispatch/qualityHelpers.ts')
function validRow() { const row=preview.manualPreview('2026-10-10'); Object.assign(row.data,{store_id:1,period:'MORNING',quantity:'320.12'}); return row }
test('missing fields cannot be silently confirmed',()=>{ assert.ok(preview.previewErrors(preview.manualPreview('')).length>=4) })
test('human edits are submitted with kg and actual ids',()=>{ const row=validRow(); assert.equal(preview.previewErrors(row).length,0); assert.equal(preview.previewPayload(row).quantity,320.12); assert.equal(preview.previewPayload(row).store_id,1) })
test('confirmation payload has no retired category or temperature fields',()=>{ const row=validRow(); assert.equal(preview.previewErrors(row).length,0); const payload=preview.previewPayload(row); for(const key of ['cargo_category_id','requires_temperature_control','min_temperature','max_temperature']) assert.equal(key in payload,false) })
test('invalid weights are rejected',()=>{ for(const value of ['-1','NaN','0','1.111']) { const row=validRow(); row.data.quantity=value; assert.ok(preview.previewErrors(row).length>0) } })
const report={delivery_date:'2026-10-10',basis_hash:'same',rule_version:'v1',utilization_target:.8,basis_origin:'FROZEN_INPUT',total_score:100,metrics:{valid_demand_count:4,assigned_demand_count:2}}
test('comparison guards date, scope, rules, parameters and unscorable',()=>{ assert.equal(quality.comparableReports([report,report]),true); for(const changes of [{basis_hash:'different'},{rule_version:'v2'},{delivery_date:'2026-10-11'},{utilization_target:.9},{basis_origin:'LEGACY_RECONSTRUCTED'},{total_score:null}]) assert.equal(quality.comparableReports([report,{...report,...changes}]),false) })
test('zero demands have no fake excellent rating',()=>{ assert.equal(quality.scoreLabel({...report,total_score:null}),'无法评分'); assert.equal(quality.allocationRate({...report,metrics:{valid_demand_count:0}}),0) })
test('entry routes and permissions preserve existing operations',()=>{
  const view=readFileSync(new URL('../src/views/operations/DeliveryDemandView.vue',import.meta.url),'utf8')
  assert.ok(view.includes("authStore.user?.role === 'ADMIN'")); assert.ok(view.includes('DeliveryDemandFormDialog'))
  const reportView=readFileSync(new URL('../src/views/dispatch/DispatchQualityView.vue',import.meta.url),'utf8')
  assert.ok(reportView.includes('token === version')); assert.ok(reportView.includes('auth.canOperate')); assert.ok(reportView.includes('window.print()'))
  const detailView=readFileSync(new URL('../src/views/dispatch/DispatchPlanDetailView.vue',import.meta.url),'utf8')
  assert.ok(detailView.includes('qualitySnapshot.dimensions')); assert.ok(detailView.includes('deduction_reasons'))
})
