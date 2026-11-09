<script setup lang="ts">
import {onMounted, ref} from 'vue'
import http from '@/api/http'
import {useAuthStore} from '@/stores/auth'
import {ElMessageBox} from 'element-plus'
interface Case {id:number; source_key:string; category:string; reason:string; status:string; responsible_user_id:number|null; resolution:string|null; revision:number}
interface Event {id:number; actor_id:number; before_status:string|null; after_status:string; note:string; created_at:string}
const auth = useAuthStore(), rows = ref<Case[]>([]), events = ref<Event[]>([]), error = ref(''), busy = ref(false), offset = ref(0)
const filter = ref(''), category = ref('UNASSIGNED_DEMAND'), objectId = ref<number|null>(null), responsible = ref<number|null>(null)
const categories = [{value:'UNASSIGNED_DEMAND', label:'未分配需求'}, {value:'FAILED_STOP',label:'配送失败'}, {value:'MISSING_PROOF',label:'缺少回单'}, {value:'REJECTED_PROOF',label:'回单驳回'}, {value:'VEHICLE_UNAVAILABLE',label:'任务资源或约束异常'}, {value:'STATE_CONFLICT',label:'业务状态冲突'}]
const caseStatusLabels: Record<string, string> = { OPEN: '待处理', IN_PROGRESS: '处理中', RESOLVED: '已解决' }
const caseStatus = (status: string | null) => status ? caseStatusLabels[status] ?? status : '—'
async function load() { busy.value=true; error.value=''; try { rows.value=(await http.get<Case[]>('/exception-cases',{params:{status:filter.value || undefined,offset:offset.value,limit:20}})).data } catch(e) { error.value=(e as Error).message } finally {busy.value=false} }
async function create() { if(!auth.canOperate || busy.value || !objectId.value)return;busy.value=true;error.value='';try {await http.post('/exception-cases',{category:category.value,object_id:objectId.value,responsible_user_id:responsible.value});await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false} }
async function update(item:Case,status:string) {
  if(!auth.canOperate || busy.value)return
  busy.value=true
  let note:string; try {note=(await ElMessageBox.prompt('填写处理说明。关闭工单不会修改签收、失败或回单事实。','处理异常',{inputValidator:(v:string)=>!!v.trim() || '请填写说明'})).value} catch {busy.value=false;return}
  busy.value=true;error.value='';try {await http.patch(`/exception-cases/${item.id}`,{revision:item.revision,status,responsible_user_id:responsible.value ?? item.responsible_user_id,note});await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}
}
async function showEvents(id:number){try{events.value=(await http.get<Event[]>(`/exception-cases/${id}/events`)).data}catch(e){error.value=(e as Error).message}}
async function page(delta:number){offset.value=Math.max(0,offset.value+delta);await load()}
onMounted(load)
</script>
<template><section><h1>异常处理工单</h1><p>按真实业务记录登记异常。编号分别为需求、停靠点、回单或任务 ID；后端独立验证异常条件。责任人填写启用的管理员或调度员 ID。</p>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <el-card v-if="auth.canOperate"><el-select v-model="category"><el-option v-for="c in categories" :key="c.value" :label="c.label" :value="c.value" /></el-select><el-input-number v-model="objectId" :min="1" placeholder="业务记录 ID" /><el-input-number v-model="responsible" :min="1" placeholder="责任人 ID" /><el-button :disabled="!objectId || busy" @click="create">登记异常</el-button></el-card>
  <el-card><el-select v-model="filter" clearable placeholder="全部状态" @change="offset=0;load()"><el-option label="待处理" value="OPEN" /><el-option label="处理中" value="IN_PROGRESS" /><el-option label="已解决" value="RESOLVED" /></el-select><el-button :loading="busy" @click="load">刷新</el-button>
    <el-table :data="rows"><template #empty><el-empty description="暂无异常工单" /></template><el-table-column prop="source_key" label="业务记录" /><el-table-column prop="reason" label="异常事实" /><el-table-column label="状态"><template #default="{row}"><span :title="row.status">{{ caseStatus(row.status) }}</span></template></el-table-column><el-table-column prop="responsible_user_id" label="责任人 ID" /><el-table-column prop="resolution" label="解决说明" /><el-table-column label="操作" min-width="220"><template #default="{row}"><el-button link @click="showEvents(row.id)">处理记录</el-button><el-button v-if="row.status !== 'RESOLVED'" link :disabled="busy" @click="update(row,'IN_PROGRESS')">处理 / 指派</el-button><el-button v-if="row.status === 'IN_PROGRESS'" link :disabled="busy" @click="update(row,'RESOLVED')">解决</el-button><el-button v-if="row.status === 'RESOLVED'" link :disabled="busy" @click="update(row,'OPEN')">重开</el-button></template></el-table-column></el-table>
    <el-button :disabled="offset===0 || busy" @click="page(-20)">上一页</el-button><el-button :disabled="rows.length<20 || busy" @click="page(20)">下一页</el-button>
  </el-card><el-card v-if="events.length"><h2>处理历史</h2><el-table :data="events"><el-table-column prop="created_at" label="时间" /><el-table-column prop="actor_id" label="操作人 ID" /><el-table-column label="此前状态"><template #default="{row}"><span :title="row.before_status">{{ caseStatus(row.before_status) }}</span></template></el-table-column><el-table-column label="随后状态"><template #default="{row}"><span :title="row.after_status">{{ caseStatus(row.after_status) }}</span></template></el-table-column><el-table-column prop="note" label="说明" /></el-table></el-card>
</section></template>
<style scoped>section{max-width:1600px;margin:auto}.el-card{margin:16px 0}.el-select{width:220px}.el-button,.el-input-number{margin:8px}p{color:#56657a}</style>
