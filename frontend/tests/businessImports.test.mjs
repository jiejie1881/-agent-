import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import {computed,ref} from 'vue'
import test from 'node:test'
function page(api,auth={canOperate:true,canManageMasterData:true},confirm=async()=>true){
  const source=readFileSync(new URL('../src/views/operations/BusinessImportView.vue',import.meta.url),'utf8').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const compiled=ts.transpileModule(source+'\nexport {preview,confirm,refresh,batch,busy,file,kind,error,canConfirm}',{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText
  const module={exports:{}}
  const deps={vue:{computed,ref,onMounted(){}},'vue-router':{useRoute:()=>({query:{}}),useRouter:()=>({replace:async()=>{}})},'@/stores/auth':{useAuthStore:()=>auth},'@/api/business-imports':api,'element-plus':{ElMessageBox:{confirm}}}
  vm.runInNewContext(compiled,{module,exports:module.exports,require:name=>deps[name],Number,Object});return module.exports
}
const batch={id:1,kind:'stores',status:'PREVIEW',rows:[{code:'S'}],errors:[],result_ids:[]}
test('import preview writes no business confirmation and preserves batch',async()=>{
  let calls=0;const p=page({previewImport:async()=>({data:batch}),confirmImport:async()=>calls++,listImportBatches:async()=>({data:[]})})
  p.file.value={name:'s.csv'};await p.preview();assert.equal(p.batch.value.id,1);assert.equal(calls,0);assert.equal(p.busy.value,false)
})
test('import confirm cancellation and duplicate dialog guard',async()=>{
  let finish,calls=0;const p=page({confirmImport:async()=>calls++},undefined,()=>new Promise((_,reject)=>{finish=reject}))
  p.batch.value=batch;const pending=p.confirm();assert.equal(p.busy.value,true);await p.confirm();finish(new Error('cancel'));await pending
  assert.equal(calls,0);assert.equal(p.busy.value,false)
})
test('import timeout restores authoritative persisted outcome',async()=>{
  const p=page({confirmImport:async()=>{throw {message:'请求超时'}},getImportBatch:async()=>({data:{...batch,status:'IMPORTED',result_ids:[7]}})})
  p.batch.value=batch;await p.confirm();assert.equal(p.batch.value.status,'IMPORTED');assert.equal(p.busy.value,false);assert.match(p.error.value,/请求超时/)
})
test('viewer and dispatcher cannot submit master imports',async()=>{
  let calls=0;for(const auth of [{canOperate:false,canManageMasterData:false},{canOperate:true,canManageMasterData:false}]){
    const p=page({previewImport:async()=>calls++,confirmImport:async()=>calls++},auth);p.kind.value='stores';p.file.value={name:'s.csv'};p.batch.value=batch
    await p.preview();await p.confirm();assert.equal(p.canConfirm.value,false)
  }assert.equal(calls,0)
})
test('map has no fixed depot, fake estimates or public routing transport',()=>{
  const source=readFileSync(new URL('../src/views/dispatch/components/DispatchRouteMap.vue',import.meta.url),'utf8')
  assert.doesNotMatch(source,/router\.project-osrm|deliveryCenter|岳麓|distanceKm: 0/)
  assert.match(source,/store_latitude/);assert.match(source,/VITE_MAP_TILE_URL/)
})
