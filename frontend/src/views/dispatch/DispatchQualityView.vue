<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { qualityHistory, generateQualityReport, compareQualityReports, summarizeQualityReport } from '@/api/ai-operations'
import { getDispatchPlan } from '@/api/dispatch-plans'
import { loadDashboardPlans } from '@/api/dashboard'
import type { QualityReport, QualityComparison } from '@/types/ai-operations'
import type { DispatchPlanSummary } from '@/types/dispatch-plan'
import { selectCurrentPlan } from '@/views/dashboard/metrics'
import { useAuthStore } from '@/stores/auth'
import { dimensionLabels, percent, allocationRate, scoreLabel } from './qualityHelpers'
import { businessRef, planRef } from '@/utils/businessLabels'
const route = useRoute(), router = useRouter(), auth = useAuthStore()
const today = new Date(), date = ref(`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`)
const plans = ref<DispatchPlanSummary[]>([]), planId = ref<number>(), history = ref<QualityReport[]>([]), reportId = ref<number>()
const loading = ref(false), scoring = ref(false), summarizing = ref(false), comparing = ref(false), error = ref(''), actionError = ref('')
const basket = ref<QualityReport[]>([]), comparison = ref<QualityComparison | null>(null), aiSummary = ref<QualityReport['summary'] | null>(null)
let version = 0
const report = computed(() => history.value.find(r => r.id === reportId.value) ?? null)
const taskEntity = (id?: number) => report.value?.entities?.tasks.find(t => t.order_id === id)
const demandEntity = (id?: number) => report.value?.entities?.demands.find(d => d.id === id)
const taskName = (id?: number) => taskEntity(id)?.task_code ?? businessRef('TASK', id, report.value?.delivery_date)
const demandName = (id?: number) => { const d = demandEntity(id); return d ? `${d.store_name} · ${d.code}` : businessRef('DEM', id, report.value?.delivery_date) }
function message(e: unknown) { return e && typeof e === 'object' && 'message' in e ? String(e.message) : '加载失败，请重试' }
async function loadHistory(id: number, token: number) {
  const { data } = await qualityHistory(id)
  if (version === token) { history.value = data; reportId.value = data[0]?.id }
}
async function loadDate(preferred?: number) {
  const token = ++version, queryDate = date.value
  plans.value = []; history.value = []; planId.value = undefined; reportId.value = undefined; basket.value = []; comparison.value = null; aiSummary.value = null
  loading.value = true; error.value = ''; actionError.value = ''
  try {
    const data = await loadDashboardPlans(queryDate, () => token === version)
    if (token !== version) return
    plans.value = data
    planId.value = data.find(p => p.id === preferred)?.id ?? selectCurrentPlan(data)?.id
    if (planId.value) await loadHistory(planId.value, token)
  } catch (e) { if (token === version) error.value = message(e) }
  finally { if (token === version) loading.value = false }
}
async function selectPlan() {
  const token = ++version; history.value = []; reportId.value = undefined; aiSummary.value = null; error.value = ''; actionError.value = ''; loading.value = true
  try { if (planId.value) await loadHistory(planId.value, token) } catch (e) { if (token === version) error.value = message(e) }
  finally { if (token === version) loading.value = false }
}
async function rescore() {
  if (!planId.value || scoring.value) return
  const token = version, id = planId.value; scoring.value = true; actionError.value = ''
  try { const { data } = await generateQualityReport(id); if (token === version) { history.value.unshift(data); reportId.value = data.id; aiSummary.value = null } }
  catch (e) { if (token === version) actionError.value = message(e) }
  finally { scoring.value = false }
}
async function summarize() {
  if (!report.value || summarizing.value) return
  const token = version, r = report.value; summarizing.value = true; actionError.value = ''
  try { const { data } = await summarizeQualityReport(r.plan_id, r.id); if (token === version && report.value?.id === r.id) aiSummary.value = data }
  catch (e) { if (token === version) actionError.value = message(e) }
  finally { summarizing.value = false }
}
function addComparison() {
  if (report.value && basket.value.length < 5 && !basket.value.some(r => r.id === report.value!.id)) { basket.value.push(report.value); comparison.value = null }
}
async function compare() {
  const token = version; comparing.value = true; actionError.value = ''
  try { const { data } = await compareQualityReports(basket.value.map(r => r.id)); if (token === version) comparison.value = data }
  catch (e) { if (token === version) actionError.value = message(e) }
  finally { comparing.value = false }
}
function printReport() { window.print() }
onMounted(async () => {
  const id = Number(route.query.planId)
  if (id) {
    try { date.value = (await getDispatchPlan(id)).data.delivery_date } catch (e) { error.value = message(e); return }
  }
  await loadDate(id || undefined)
})
onBeforeUnmount(() => { version++ })
</script>

<template>
  <section class="quality-page">
    <div class="quality-heading"><div><p>派车中心 / 确定性规则评分</p><h1>智能调度质量报告</h1><span>真实业务快照 · AI 仅提供建议 · 分数不能替代发布校验</span></div><el-button class="no-print" :disabled="!report" @click="printReport">打印 / 保存 PDF</el-button></div>
    <el-card class="no-print" shadow="never"><div class="quality-toolbar">
      <el-date-picker v-model="date" type="date" value-format="YYYY-MM-DD" :clearable="false" :disabled="scoring" @change="loadDate()" />
      <el-select v-model="planId" placeholder="选择方案版本" :disabled="loading || scoring" @change="selectPlan"><el-option v-for="p in plans" :key="p.id" :label="`V${p.version} · ${p.status} · #${p.id}${p.status === 'CANCELLED' ? '（历史）' : ''}`" :value="p.id" /></el-select>
      <el-select v-model="reportId" placeholder="历史报告" :disabled="loading || scoring" @change="aiSummary = null"><el-option v-for="r in history" :key="r.id" :label="`报告 #${r.id} · ${new Date(r.generated_at).toLocaleString()}`" :value="r.id" /></el-select>
      <el-button :loading="loading" :disabled="scoring" @click="loadDate(planId)">刷新</el-button><el-button v-if="auth.canOperate" type="primary" :loading="scoring" :disabled="!planId || loading" @click="rescore">{{ history.length ? '重新评分' : '生成评分' }}</el-button>
    </div></el-card>
    <el-alert v-if="error || actionError" :title="error || actionError" type="error" :closable="false" />
    <div v-loading="loading" class="quality-content">
      <el-empty v-if="!report && !loading" :description="!plans.length ? '当天没有方案，请先录入需求并自动派车' : '该版本暂无质量报告。可以生成评分；旧方案将标记为临时评分。'" />
      <template v-if="report">
        <div class="report-meta">{{ report.entities?.plan_code ?? planRef(report.delivery_date, report.plan_version) }} · 评分时状态 {{ report.plan_status_at_scoring }}<br>报告 #{{ report.id }} · {{ report.generated_at }} · {{ report.rule_version }} · 内部方案ID {{ report.plan_id }}</div>
        <el-alert v-if="report.plan_status_at_scoring === 'CANCELLED'" title="已取消方案，仅作为历史查询，不是当前执行方案" type="warning" :closable="false" />
        <div class="quality-hero"><div class="score"><span>综合评分</span><strong>{{ scoreLabel(report) }}</strong><el-tag>{{ report.grade ?? '无等级' }}</el-tag><p>{{ report.status }} · 评分覆盖率 {{ report.coverage === null ? '原始范围未知' : percent(report.coverage) }}</p></div><div><h3>发布校验 {{ report.publication_validation === 'PASS' ? '通过（评分时刻）' : '不通过' }}</h3><p>任何高分都不能绕过正式发布校验。</p><p v-for="reason in report.unscorable_reasons" :key="reason">{{ reason }}</p><el-button class="no-print" @click="router.push(`/dispatch/plans/${report.plan_id}`)">返回方案 · 人工调整 / 发布</el-button></div></div>
        <div class="dimension-grid"><el-card v-for="d in report.dimensions" :key="d.key" shadow="never"><div class="dimension-title"><strong>{{ dimensionLabels[d.key] }}</strong><b>{{ d.score }} / {{ d.max_score }}</b></div><el-progress :percentage="Math.round(d.score / d.max_score * 100)" :show-text="false" /><p>扣分 {{ d.deduction }}</p><p v-for="reason in d.deduction_reasons" :key="reason">{{ reason }}</p><small v-for="formula in d.formula" :key="formula">{{ formula }}</small></el-card></div>
        <div class="stats"><div>需求条数分配率<strong>{{ percent(allocationRate(report)) }}</strong></div><div>已分配 / 有效货量 (kg)<strong>{{ report.metrics.assigned_quantity }} / {{ report.metrics.valid_quantity }}</strong></div><div>车辆 / 趟次<strong>{{ report.metrics.vehicle_count }} / {{ report.metrics.trip_count }}</strong></div><div>平均装载率<strong>{{ percent(report.metrics.average_load_ratio) }}</strong></div><div>未分配 / 异常案例<strong>{{ report.metrics.unassigned_count }} / {{ report.metrics.exception_count }}</strong></div></div>
        <el-card shadow="never"><h3>运力与司机准备度</h3><p>低装载趟次（低于50%）：{{ report.metrics.low_load_trip_count }}；历史报告若无实体快照，明确显示未记录，不补造名称。</p><el-table :data="report.trips" stripe>
          <el-table-column label="配送任务" min-width="180"><template #default="{row}"><router-link :to="`/dispatch/plans/${report.plan_id}`">{{ taskName(row.order_id) }}</router-link></template></el-table-column>
          <el-table-column label="车辆 / 车型" min-width="230"><template #default="{row}">{{ taskEntity(row.order_id)?.vehicle.plate_number ?? '车牌未记录' }}<br>{{ taskEntity(row.order_id)?.vehicle.code ?? '编号未记录' }} · {{ taskEntity(row.order_id)?.vehicle.type_name ?? '车型未记录' }}</template></el-table-column>
          <el-table-column label="实际司机" min-width="150"><template #default="{row}">{{ taskEntity(row.order_id)?.driver?.name ?? '司机未记录' }}<br>{{ taskEntity(row.order_id)?.driver?.employee_code ?? '—' }}</template></el-table-column>
          <el-table-column label="配送线路 / 门店" min-width="210"><template #default="{row}">{{ taskEntity(row.order_id)?.route.name ?? '线路未记录' }}<br>{{ taskEntity(row.order_id)?.stores.map(s => s.name).join('、') ?? '门店未记录' }}</template></el-table-column>
          <el-table-column label="时段 / 趟次" min-width="120"><template #default="{row}">{{ row.period === 'MORNING' ? '上午' : '下午' }} / 第{{ row.trip_no }}趟</template></el-table-column>
          <el-table-column label="实际 / 最大 kg" min-width="130"><template #default="{row}">{{ row.actual_load }} / {{ row.max_load }}</template></el-table-column><el-table-column label="装载率"><template #default="{row}">{{ percent(row.load_ratio) }}</template></el-table-column><el-table-column label="司机准备"><template #default="{row}"><el-tag :type="row.ready ? 'success' : 'danger'">{{ row.ready ? '可执行' : row.driver_readiness.availability_status }}</el-tag></template></el-table-column><template #empty>无车辆任务，利用率和司机准备度不按满分计算</template></el-table></el-card>
        <el-card shadow="never"><h3>强制约束问题与风险</h3><el-table :data="report.issues"><el-table-column prop="category" label="类别" width="110" /><el-table-column prop="code" label="问题代码" min-width="180" /><el-table-column label="任务" min-width="180"><template #default="{row}">{{ row.order_id ? taskName(row.order_id) : '方案级问题' }}</template></el-table-column><el-table-column label="门店需求" min-width="210"><template #default="{row}">{{ row.delivery_demand_id ? demandName(row.delivery_demand_id) : '—' }}</template></el-table-column><el-table-column prop="message" label="明确原因" min-width="260" /><template #empty>评分时未发现发布约束问题；正式发布仍需重检</template></el-table></el-card>
        <el-card shadow="never"><h3>未分配需求原因</h3><el-table :data="report.unassigned"><el-table-column label="门店 / 需求编号" min-width="270"><template #default="{row}">{{ demandName(row.demand_id) }}</template></el-table-column><el-table-column label="原因"><template #default="{row}">{{ row.reasons.join('；') || '原因缺失，需要人工核对' }}</template></el-table-column><template #empty>无未分配需求</template></el-table></el-card>
        <el-card shadow="never"><div class="dimension-title"><h3>分析与优化建议</h3><el-button v-if="auth.canOperate" class="no-print" :loading="summarizing" @click="summarize">生成 AI 建议</el-button></div><el-tag>{{ aiSummary?.mode ?? report.summary.mode }}</el-tag><p>{{ report.summary.text }}</p><el-alert v-if="aiSummary?.ai_commentary" :title="aiSummary.ai_commentary" description="模型文字为待验证建议，不改变数值、权限或方案；执行调整请返回方案按正式流程操作。" type="info" :closable="false" /><ul><li v-for="s in (aiSummary ?? report.summary).suggestions" :key="s">{{ s }}</li></ul><small v-if="aiSummary?.mode === 'RULE_TEMPLATE'">模型不可用或格式不符合要求，已安全降级为规则模板。</small></el-card>
        <el-card shadow="never"><h3>评分基准与限制</h3><p>基准来源：{{ report.basis_origin }} · 装载率目标 {{ percent(report.utilization_target) }}</p><code>{{ report.basis_hash }}</code><p v-for="n in report.notices" :key="n">{{ n }}</p></el-card>
        <el-card shadow="never"><div class="dimension-title"><h3>历史与版本对比</h3><el-button class="no-print" :disabled="basket.length >= 5 || basket.some(r => r.id === report!.id)" @click="addComparison">加入当前报告</el-button></div><p>依次选择同日期的方案版本及历史报告并加入对比（2–5份）。历史评分不会因新版本生成而改变。</p><div class="quality-toolbar no-print"><el-tag v-for="r in basket" :key="r.id" closable @close="basket = basket.filter(x => x.id !== r.id); comparison = null">V{{ r.plan_version }} · 报告 #{{ r.id }}</el-tag><el-button :disabled="basket.length < 2" :loading="comparing" @click="compare">对比报告</el-button></div>
          <template v-if="comparison"><el-alert :title="comparison.notice" :type="comparison.comparable ? 'success' : 'warning'" :closable="false" /><div v-if="comparison.comparable" class="score-bars"><div v-for="r in comparison.reports" :key="r.id">V{{ r.plan_version }} / #{{ r.id }}<el-progress :percentage="r.total_score ?? 0" :format="(p: number) => `${p} 分`" /></div></div><el-table :data="comparison.reports"><el-table-column label="版本 / 评分时状态"><template #default="{row}">V{{ row.plan_version }} / {{ row.plan_status_at_scoring }}</template></el-table-column><el-table-column prop="total_score" label="总分" /><el-table-column label="分配率"><template #default="{row}">{{ percent(allocationRate(row)) }}</template></el-table-column><el-table-column prop="metrics.assigned_quantity" label="货量 kg" /><el-table-column prop="metrics.vehicle_count" label="车辆" /><el-table-column prop="metrics.trip_count" label="趟次" /><el-table-column label="装载率"><template #default="{row}">{{ percent(row.metrics.average_load_ratio) }}</template></el-table-column><el-table-column prop="metrics.unassigned_count" label="未分配" /><el-table-column prop="metrics.exception_count" label="异常" /><el-table-column v-for="(label,key) in dimensionLabels" :key="key" :label="label" min-width="135"><template #default="{row}">{{ row.dimensions.find((d: {key: string}) => d.key === key)?.score ?? '—' }}</template></el-table-column></el-table></template>
        </el-card>
      </template>
    </div>
  </section>
</template>
<style scoped>
.quality-page { padding:24px;display:grid;gap:18px;color:#243954 }.quality-heading,.dimension-title { display:flex;align-items:center;justify-content:space-between;gap:16px }.quality-heading p,.quality-heading span { color:#788ba8 }.quality-heading h1 { font-size:30px;margin:8px 0 }.quality-toolbar { display:flex;gap:12px;flex-wrap:wrap }.quality-toolbar .el-select { width:260px }.quality-content { display:grid;gap:18px;min-height:220px }.report-meta { font-size:13px;line-height:1.8;color:#6b7e97 }.quality-hero { border-radius:16px;background:linear-gradient(120deg,#163357,#2870bd);color:white;display:grid;grid-template-columns:1fr 1.3fr;padding:30px;gap:25px }.score strong { display:block;font-size:38px;margin:12px 0 }.dimension-grid { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px }.dimension-grid p { font-size:13px;color:#b77b37 }.dimension-grid small { display:block;line-height:1.8;color:#71809a }.stats { display:grid;grid-template-columns:repeat(5,1fr);gap:12px }.stats div { background:white;border:1px solid #e5ebf3;border-radius:12px;padding:16px;font-size:13px;color:#76869d }.stats strong { display:block;color:#243954;font-size:21px;margin-top:12px }code { overflow-wrap:anywhere;font-size:12px }.score-bars { display:grid;gap:12px;margin:20px 0 }@media(max-width:1000px){.dimension-grid{grid-template-columns:repeat(2,1fr)}.stats{grid-template-columns:repeat(2,1fr)}}@media(max-width:650px){.quality-page{padding:12px}.quality-heading{align-items:flex-start}.quality-hero,.dimension-grid,.stats{grid-template-columns:1fr}.quality-heading h1{font-size:24px}}
</style>
<style>
@media print {
  html:has(.quality-page), body:has(.quality-page), #app:has(.quality-page) { min-width:0!important }
  .quality-page { width:100%;max-width:100% }
  .quality-page .el-table { font-size:10px }
  .quality-page .el-table .cell { padding:0 3px;overflow-wrap:anywhere }
}
@media print { .app-sidebar,.app-header,.quality-page .no-print { display:none!important } .admin-layout__body { margin-left:0!important } .admin-layout__main,.quality-page { padding:0!important } .quality-page .el-card,.quality-hero { break-inside:avoid;box-shadow:none } .quality-page .el-table { overflow:visible } .quality-page .el-table__body-wrapper { overflow:visible!important } .quality-page { print-color-adjust:exact } }
</style>
