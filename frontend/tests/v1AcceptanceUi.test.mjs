import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
test('Agent drafts hide traditional publish and guard its handler',()=>{
 const s=readFileSync(new URL('../src/views/dispatch/DispatchPlanDetailView.vue',import.meta.url),'utf8')
 assert.match(s,/async function handlePublish\(\)\s*\{\s*if \(!plan\.value \|\| plan\.value\.source === 'AGENT'/)
 assert.match(s,/<el-button\s+v-if="plan\.source !== 'AGENT'"[\s\S]*?@click="handlePublish"/)
})
test('dashboard delivery quantity uses the documented kg unit',()=>{
 const s=readFileSync(new URL('../src/views/dashboard/DashboardView.vue',import.meta.url),'utf8')
 assert.match(s,/title="当日配送总货量"[^\n]*unit="kg"/)
 assert.doesNotMatch(s,/系统未定义 kg\/件/)
})
test('driver login and restored session stay outside the management UI',()=>{
 const s=readFileSync(new URL('../src/views/LoginView.vue',import.meta.url),'utf8')
 assert.match(s,/authStore\.user\?\.role === 'DRIVER'[\s\S]*?authStore\.logout\(\)[\s\S]*?司机账号请使用司机端登录/)
 const store=readFileSync(new URL('../src/stores/auth.ts',import.meta.url),'utf8')
 assert.match(store,/getCurrentUser\(\)[\s\S]*?user\.value\.role === 'DRIVER'\) logout\(\)/)
})
test('uncertain import confirmation refreshes both the batch and history',()=>{
 const s=readFileSync(new URL('../src/views/operations/BusinessImportView.vue',import.meta.url),'utf8')
 assert.match(s,/请求超时后请刷新批次[\s\S]*?await openBatch\(batch\.value\.id\); await loadHistory\(\)/)
})
