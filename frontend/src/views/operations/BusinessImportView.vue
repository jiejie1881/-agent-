<script setup lang="ts">
import {computed, onMounted, ref} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {ElMessageBox} from 'element-plus'
import {useAuthStore} from '@/stores/auth'
import {confirmImport, downloadImportTemplate, getImportBatch, listImportBatches, previewImport, type ImportBatch, type ImportKind} from '@/api/business-imports'
const columnLabels: Record<string,string> = {code:'业务编码',name:'名称',address:'地址',contact_name:'联系人',contact_phone:'联系电话',delivery_region:'所属区域',longitude:'经度',latitude:'纬度',route_codes:'关联线路编码',start_address:'起点地址',end_address:'终点地址',geographic_notes:'道路地形说明',distance_km:'距离公里',duration_minutes:'预计分钟',route_data_source:'资料来源',plate_number:'车牌或验收标识',vehicle_type_code:'车型内部编码',driver_username:'司机账号',organization:'所属组织',rated_load:'额定载重公斤',daily_trip_limit:'每日趟次上限',operating_status:'运行状态',allowed_route_codes:'允许线路编码',date:'配送日期',store_code:'门店编码',period:'配送时段',quantity:'需求重量公斤',priority:'优先级'}
const kindLabels: Record<string,string> = {stores:'门店',routes:'线路',vehicles:'车辆',demands:'配送需求'}
const statusLabels: Record<string,string> = {PREVIEW:'待人工确认',INVALID:'校验失败',IMPORTED:'导入成功'}
function cellValue(value: string) { return ({MORNING:'上午',AFTERNOON:'下午',NORMAL:'普通',HIGH:'高',URGENT:'加急',ACTIVE:'正常',MAINTENANCE:'维修',RETIRED:'退役'} as Record<string,string>)[value] ?? value }
const auth = useAuthStore(), route = useRoute(), router = useRouter()
const kind = ref<ImportKind>('demands'), batch = ref<ImportBatch | null>(null), history = ref<ImportBatch[]>([])
const file = ref<File | null>(null), busy = ref(false), error = ref(''), offset = ref(0)
const kinds = computed(() => auth.canManageMasterData ? [{value:'stores', label:'门店'}, {value:'routes',label:'线路'}, {value:'vehicles',label:'车辆'}, {value:'demands',label:'配送需求'}] : [{value:'demands',label:'配送需求'}])
const canConfirm = computed(() => batch.value?.status === 'PREVIEW' && !batch.value.errors.length && auth.canOperate && (batch.value.kind === 'demands' || auth.canManageMasterData) && !busy.value)
function selected(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] ?? null }
async function loadHistory() { history.value = (await listImportBatches(offset.value)).data }
async function openBatch(id: number) { batch.value = (await getImportBatch(id)).data; await router.replace({query: {...route.query, batch: id}}) }
async function preview() {
  if (!file.value || busy.value || !auth.canOperate || (kind.value !== 'demands' && !auth.canManageMasterData)) return
  busy.value = true; error.value = ''
  try { const {data} = await previewImport(kind.value, file.value); batch.value = data; await router.replace({query: {batch: data.id}}); await loadHistory() }
  catch(e) { error.value = (e as Error).message || '预览失败，请重试' }
  finally { busy.value = false }
}
async function confirm() {
  if (!batch.value || !canConfirm.value) return
  busy.value = true
  try { await ElMessageBox.confirm(`确认将 ${batch.value.rows.length} 行业务数据保存到数据库？系统将重新校验，任一行失败则整批回滚。`, '人工确认导入', {type:'warning'}) } catch { busy.value = false; return }
  error.value = ''
  try { batch.value = (await confirmImport(batch.value.id)).data; await loadHistory() }
  catch(e) { error.value = `${(e as Error).message || '请求失败'}。请求超时后请刷新批次，确认结果后再重试。`; try { await openBatch(batch.value.id); await loadHistory() } catch {} }
  finally { busy.value = false }
}
async function refresh() {
  busy.value = true; error.value = ''
  try { if (batch.value) await openBatch(batch.value.id); await loadHistory() }
  catch(e) { error.value = (e as Error).message || '加载失败' } finally { busy.value = false }
}
async function page(delta: number) { offset.value = Math.max(0, offset.value + delta); await refresh() }
onMounted(async () => { try { const id = Number(route.query.batch); if (Number.isInteger(id) && id > 0) await openBatch(id); await loadHistory() } catch(e) { error.value = (e as Error).message || '批次加载失败' } })
</script>
<template>
  <section><h1>业务数据导入</h1><p>先下载空白模板，填写真实业务资料。上传只生成预览，人工确认后才保存。每批最多 1000 行、5MB。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-card v-if="auth.canOperate"><el-select v-model="kind"><el-option v-for="item in kinds" :key="item.value" :label="item.label" :value="item.value" /></el-select>
      <el-button @click="downloadImportTemplate(kind,'csv')">CSV 空白模板</el-button><el-button @click="downloadImportTemplate(kind,'xlsx')">XLSX 空白模板</el-button>
      <input type="file" accept=".csv,.xlsx" :disabled="busy" @change="selected" /><el-button type="primary" :disabled="!file || busy" @click="preview">上传并预览</el-button>
      <p>编码引用必须已存在且启用；多线路编码用 | 分隔。距离、时间为人工提供的数据，必须注明来源。空白车辆线路范围表示不额外限制线路。</p>
    </el-card>
    <el-card v-if="batch"><h2>批次 #{{ batch.id }} · {{ batch.status === 'IMPORTED' ? '导入成功' : batch.status === 'INVALID' ? '校验失败' : '待人工确认' }}</h2>
      <p>预览有效期至 {{ batch.expires_at }} · {{ batch.rows.length }} 行 · 保存记录 {{ batch.result_ids.length }} 条</p>
      <el-table v-if="batch.errors.length" :data="batch.errors"><el-table-column prop="row" label="文件行号" /><el-table-column prop="message" label="错误原因" /></el-table>
      <el-table :data="batch.rows"><el-table-column v-for="column in Object.keys(batch.rows[0] ?? {})" :key="column" :prop="column" :label="columnLabels[column] ?? column" min-width="130"><template #default="{row}">{{ ['period','priority','operating_status'].includes(column) ? cellValue(row[column]) : row[column] }}</template></el-table-column></el-table>
      <el-button type="primary" :disabled="!canConfirm" :loading="busy" @click="confirm">人工确认导入</el-button><el-button :disabled="busy" @click="refresh">刷新批次状态</el-button>
    </el-card>
    <el-card><h2>我的导入记录</h2><el-table :data="history"><template #empty><el-empty description="暂无导入记录" /></template><el-table-column prop="id" label="批次" /><el-table-column label="类型"><template #default="{row}">{{ kindLabels[row.kind] ?? row.kind }}</template></el-table-column><el-table-column label="状态"><template #default="{row}">{{ statusLabels[row.status] ?? row.status }}</template></el-table-column><el-table-column prop="created_at" label="创建时间" /><el-table-column label="查看"><template #default="{row}"><el-button link @click="openBatch(row.id)">查看预览与结果</el-button></template></el-table-column></el-table>
      <el-button :disabled="offset === 0 || busy" @click="page(-20)">上一页</el-button><el-button :disabled="history.length < 20 || busy" @click="page(20)">下一页</el-button>
    </el-card>
  </section>
</template>
<style scoped>section {max-width:1600px;margin:auto}.el-card {margin:16px 0}.el-button,input {margin:8px}.el-select {width:160px}p {color:#56657a}</style>
