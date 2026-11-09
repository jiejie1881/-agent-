<script setup lang="ts">
import { periodLabel } from '@/utils/businessLabels'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { acceptAgentDraft, getShadowContext, runShadowDispatch, type BusinessContext, type ShadowResult } from '@/api/agent-dispatch-shadow'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const now = new Date()
const date = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`)
const context = ref<BusinessContext | null>(null)
const result = ref<ShadowResult | null>(null)
const enabled = ref(false)
const loading = ref(false)
const running = ref(false)
const saving = ref(false)
const savedPlanId = ref<number | null>(null)
let acceptanceKey: string | null = null
const error = ref('')
const compareGreedy = ref(true)
let epoch = 0

const stores = computed(() => new Map(context.value?.stores.map(s => [s.id, s.name]) ?? []))
const vehicles = computed(() => new Map(context.value?.vehicles.map(v => [v.id, `${v.plate_number}（${v.vehicle_type_name}）`]) ?? []))
const routes = computed(() => new Map(context.value?.routes.map(r => [r.id, r.name]) ?? []))
const demands = computed(() => new Map(context.value?.demands.map(d => [d.id, `#${d.id} ${stores.value.get(d.store_id) ?? '未知门店'} ${d.quantity}kg`]) ?? []))
const availableVehicles = computed(() => context.value?.vehicles.filter(v => v.available).length ?? 0)
function unassignedReason(row: { demand_id: number; explanation: string }) {
  const demand = context.value?.demands.find(d => d.id === row.demand_id)
  if (demand) {
    const eligible = context.value?.vehicles.filter(v => v.available &&
      context.value?.shifts.some(s => s.vehicle_id === v.id && s.period === demand.period && s.available)) ?? []
    if (!eligible.length) return '该时段没有可出勤且具备有效司机班次的车辆。'
    const maxLoad = Math.max(...eligible.map(v => Number(v.max_load)))
    if (Number(demand.quantity) > maxLoad) return `需求货量 ${demand.quantity} kg 超过该时段可用车辆最大载重 ${maxLoad} kg。`
  }
  return row.explanation.trim().length >= 4 ? row.explanation : 'Agent 未提供明确原因，请复核线路、地形、车辆与司机班次。'
}
function reason(code: string) {
  const messages: Record<string, string> = {
    VALID_CANDIDATE: '候选已通过确定性规则校验；采纳草稿和正式发布仍须分别人工确认。',
    SHADOW_DISABLED: '智能派车尚未启用，请联系管理员核对模型和业务开关。',
    NO_DEMANDS: '该日期没有可规划的配送需求。',
    STALE_CONTEXT: '业务数据在预览或规划期间发生变化，请重新读取快照。',
    SHADOW_TIMEOUT: 'Agent 规划超时，未生成可用候选。',
    AGENT_MODEL_TIMEOUT: '模型响应超时，未生成可用候选。',
    AGENT_MODEL_CONNECTION_ERROR: '模型连接失败，请检查本地模型配置。',
    AGENT_MODEL_CONFIGURATION_ERROR: '模型配置不完整，请检查后端服务。',
    AGENT_MODEL_RESPONSE_ERROR: '模型返回空结果或无法解析的响应，未生成可用候选。',
    INPUT_BUDGET_EXCEEDED: '业务快照超过本次模型输入限制。',
    OUTPUT_BUDGET_EXCEEDED: '模型输出超过限制，候选未被采纳。',
    TOKEN_BUDGET_EXCEEDED: '本次 Token 预算不足，规划已停止。',
    COST_BUDGET_EXCEEDED: '本次费用预算不足，规划已停止。',
    ACCEPTANCE_CALL_BUDGET_EXCEEDED: '本轮模型调用次数已用完，规划已停止。',
    ACCEPTANCE_TOKEN_BUDGET_EXCEEDED: '本轮共享 Token 预算不足，规划已停止。',
    ACCEPTANCE_COST_BUDGET_EXCEEDED: '本轮共享费用预算不足，规划已停止。',
    COST_BUDGET_UNCONFIGURED: '费用预算配置不完整，规划已停止。',
    REVISION_LIMIT: '候选多次违反业务规则，已达到修正上限。',
    REPEATED_CANDIDATE: 'Agent 重复提交违规候选，规划已停止。',
    SHADOW_SYSTEM_ERROR: '影子规划发生内部错误，未写入业务数据。',
  }
  return messages[code] ?? code
}
function failure(value: unknown) { return (value as { message?: string })?.message || '请求失败，请检查本地服务' }
async function refresh() {
  if (running.value || !date.value || !auth.canOperate) return
  const id = ++epoch
  context.value = null; result.value = null; enabled.value = false; error.value = ''; loading.value = true
  savedPlanId.value = null; acceptanceKey = null
  try {
    const response = await getShadowContext(date.value)
    if (id === epoch) {
      enabled.value = response.data.enabled
      context.value = response.data.context
      if (!response.data.enabled) error.value = reason(response.data.reason_code ?? 'SHADOW_DISABLED')
    }
  } catch (e) { if (id === epoch) error.value = failure(e) }
  finally { if (id === epoch) loading.value = false }
}
async function start() {
  if (running.value || loading.value || !enabled.value || !context.value || !auth.canOperate) return
  const preview = context.value
  const id = ++epoch
  result.value = null; error.value = ''; running.value = true
  savedPlanId.value = null; acceptanceKey = null
  try {
    await ElMessageBox.confirm(
      `将 ${date.value} 的配送需求、运力、线路及业务约束发送至已配置模型进行只读规划。此操作可能产生费用；候选不会保存或发布。确认本次调用？`,
      '确认发送必要业务数据', { type: 'warning', confirmButtonText: '确认调用', cancelButtonText: '取消' },
    )
    if (id !== epoch) return
    const response = await runShadowDispatch({ delivery_date: date.value,
      expected_snapshot_version: preview.snapshot_version, compare_greedy: compareGreedy.value,
      authorize_external: true })
    if (id === epoch) result.value = response.data
  } catch (e) { if (id === epoch && e !== 'cancel' && e !== 'close') error.value = failure(e) }
  finally { if (id === epoch) running.value = false }
}
async function saveDraft() {
  const current = result.value
  if (saving.value || !current?.candidate || !current.acceptance_receipt ||
      !current.validation?.is_valid || current.stale_context || !auth.canOperate) return
  try {
    await ElMessageBox.confirm(
      `请复核 ${current.candidate.delivery_date} 的 ${current.candidate.trips.length} 趟分配和 ${current.candidate.unassigned.length} 笔未分配需求。确认采纳为正式草稿？保存后仍需单独人工确认才可发布。`,
      '确认保存 Agent 草稿', { type: 'warning', confirmButtonText: '确认保存草稿', cancelButtonText: '取消' },
    )
  } catch { return }
  if (result.value !== current) return
  acceptanceKey ??= crypto.randomUUID()
  saving.value = true; error.value = ''
  try {
    const response = await acceptAgentDraft(current.candidate, current.acceptance_receipt, acceptanceKey)
    savedPlanId.value = response.data.plan_id
    await router.push({ name: 'dispatch-plan-detail', params: { planId: response.data.plan_id } })
  } catch (e) { error.value = failure(e) }
  finally { saving.value = false }
}
onMounted(refresh)
onBeforeUnmount(() => { epoch++ })
</script>

<template>
  <section class="shadow-page">
    <h1>Agent 智能派车</h1>
    <el-alert title="Agent 先生成只读候选；仅在后端签发有效采纳凭据后，可经人工确认保存正式草稿。草稿不会自动发布。" type="warning" :closable="false" />
    <el-alert v-if="!auth.canOperate" title="当前账号为只读权限，无法读取规划快照、生成候选或采纳草稿。请联系管理员安排有权限的调度人员操作。" type="info" :closable="false" />
    <el-card class="controls">
      <el-date-picker v-model="date" type="date" value-format="YYYY-MM-DD" :clearable="false" :disabled="running" @change="refresh" />
      <el-button :loading="loading" :disabled="running || !auth.canOperate" @click="refresh">读取业务快照</el-button>
      <el-checkbox v-model="compareGreedy" :disabled="running">同一快照对比传统贪心算法</el-checkbox>
      <el-button type="primary" :loading="running" :disabled="!enabled || !context || loading || !auth.canOperate" @click="start">生成只读候选</el-button>
    </el-card>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-card v-if="context" class="panel">
      <h2>{{ context.delivery_date }} 业务快照</h2>
      <p>需求 {{ context.demands.length }} 笔（可规划 {{ context.demands.filter(d => d.schedulable).length }} 笔）；车辆 {{ context.vehicles.length }} 辆（标记可出勤 {{ availableVehicles }} 辆）。最终可用性还取决于司机班次和业务规则。</p>
      <el-alert v-if="!context.demands.some(d => d.schedulable)" title="该日期没有可规划需求，Agent 不会调用模型。" type="info" :closable="false" />
      <el-alert v-if="availableVehicles === 0 && context.demands.some(d => d.schedulable)" title="该日期没有标记可出勤的车辆；需求可能全部未分配。" type="warning" :closable="false" />
      <h3>配送需求</h3>
      <el-table :data="context.demands" empty-text="该日期暂无需求">
        <el-table-column prop="id" label="需求编号" width="110" />
        <el-table-column label="门店"><template #default="{ row }">{{ stores.get(row.store_id) ?? `#${row.store_id}` }}</template></el-table-column>
        <el-table-column label="时段" width="115"><template #default="{row}">{{ periodLabel(row.period) }}</template></el-table-column>
        <el-table-column prop="quantity" label="货量 kg" width="115" />
        <el-table-column label="可规划" width="100"><template #default="{ row }">{{ row.schedulable ? '是' : '否' }}</template></el-table-column>
      </el-table>
      <h3>车辆与司机班次</h3>
      <el-table :data="context.vehicles">
        <el-table-column prop="plate_number" label="车辆" />
        <el-table-column prop="vehicle_type_name" label="车型" />
        <el-table-column label="载重 kg"><template #default="{ row }">{{ row.min_load }}～{{ row.max_load }}</template></el-table-column>
        <el-table-column label="出勤" width="90"><template #default="{ row }">{{ row.available ? '可用' : '不可用' }}</template></el-table-column>
        <el-table-column label="有效司机班次"><template #default="{ row }">{{ context.shifts.filter(s => s.vehicle_id === row.id).map(s => `${s.period}: ${s.available ? `司机#${s.driver_id}` : (s.message ?? '不可用')}`).join('；') }}</template></el-table-column>
      </el-table>
      <h3>线路与地形</h3>
      <el-table :data="context.routes"><el-table-column prop="name" label="线路" /><el-table-column prop="terrain_name" label="地形" /></el-table>
    </el-card>
    <el-card v-if="running" class="panel">正在按当前快照运行 Agent 影子规划；模型超时或预算不足会停止并显示原因。</el-card>
    <el-card v-if="result" class="panel">
      <h2>影子结果：{{ result.status === 'SUCCESS' ? '规划完成' : result.status === 'REJECTED' ? '规则拒绝' : '规划受阻' }}</h2>
      <el-alert :title="reason(result.reason_code)" :type="result.status === 'SUCCESS' ? 'success' : 'warning'" :closable="false" />
      <p>{{ result.message }}｜校验 {{ result.validation?.is_valid ? '通过' : '未通过' }}｜生成 {{ result.generation_count }} 次、修正 {{ result.revision_count }} 次｜耗时 {{ result.elapsed_ms.toFixed(0) }} ms</p>
      <p>快照核验：{{ result.freshness_checked ? '已执行' : '未执行' }}；{{ result.stale_context ? '已过期，请重新读取' : '未标记过期' }}。运行编号 {{ result.run_id }} 仅用于本次诊断。</p>
      <el-button v-if="result.status === 'SUCCESS' && result.validation?.is_valid && result.acceptance_receipt && !result.stale_context && !savedPlanId"
        type="primary" :loading="saving" :disabled="running || !auth.canOperate" @click="saveDraft">采纳为正式草稿</el-button>
      <template v-if="result.candidate">
        <p>{{ result.candidate.planning_explanation }}</p>
        <h3>候选分配（以校验结果为准）</h3>
        <el-table :data="result.candidate.trips" empty-text="无分配趟次">
          <el-table-column label="车辆"><template #default="{ row }">{{ vehicles.get(row.vehicle_id) ?? `#${row.vehicle_id}` }}</template></el-table-column>
          <el-table-column label="线路"><template #default="{ row }">{{ routes.get(row.route_id) ?? `#${row.route_id}` }}</template></el-table-column>
          <el-table-column prop="driver_id" label="司机编号" width="105" />
          <el-table-column label="时段" width="105"><template #default="{row}">{{ periodLabel(row.period) }}</template></el-table-column>
          <el-table-column prop="trip_no" label="趟次" width="75" />
          <el-table-column label="配送需求"><template #default="{ row }">{{ row.demand_ids.map((id: number) => demands.get(id) ?? `#${id}`).join('；') }}</template></el-table-column>
        </el-table>
        <h3>未分配需求</h3>
        <el-table :data="result.candidate.unassigned" empty-text="没有未分配需求">
          <el-table-column label="需求"><template #default="{ row }">{{ demands.get(row.demand_id) ?? `#${row.demand_id}` }}</template></el-table-column>
          <el-table-column label="原因"><template #default="{ row }">{{ unassignedReason(row) }}</template></el-table-column>
        </el-table>
      </template>
      <h3>确定性规则校验</h3>
      <p>已分配 {{ result.validation?.assigned_count ?? 0 }} 笔；未分配 {{ result.validation?.unassigned_count ?? 0 }} 笔；{{ result.validation?.is_valid ? '所有业务约束已通过' : '存在未通过的约束' }}。</p>
      <el-table :data="result.validation?.violations ?? []" empty-text="无违规项"><el-table-column prop="violation_code" label="错误码" /><el-table-column prop="message" label="规则说明" /></el-table>
      <h3>生成与修正记录</h3>
      <div v-for="attempt in result.attempts" :key="attempt.generation" class="attempt">
        第 {{ attempt.generation }} 次：{{ attempt.validation.is_valid ? '通过' : '拒绝' }}；{{ attempt.validation.violations.map(v => `${v.violation_code}：${v.message}`).join('；') || '无违规' }}
      </div>
      <template v-if="result.comparison && result.status === 'SUCCESS' && !result.stale_context">
        <h3>同快照传统贪心对比</h3>
        <p>Agent：已分配 {{ result.metrics.assigned_count }} / {{ result.metrics.total_demands }}，使用 {{ result.metrics.used_vehicles }} 辆车。</p>
        <p v-if="result.comparison.status === 'PASS' && result.comparison.metrics">贪心：已分配 {{ result.comparison.metrics.assigned_count }} / {{ result.comparison.metrics.total_demands }}，使用 {{ result.comparison.metrics.used_vehicles }} 辆车。</p>
        <p v-else>贪心对比不可用：{{ reason(result.comparison.error_code ?? 'GREEDY_COMPARISON_ERROR') }}</p>
      </template>
    </el-card>
  </section>
</template>

<style scoped>
.shadow-page { display: grid; gap: 16px; }
.shadow-page h1, .shadow-page h2, .shadow-page h3 { margin: 0 0 12px; }
.shadow-page p { margin: 8px 0; }
.controls :deep(.el-card__body) { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.panel { min-width: 0; }
.panel h3 { margin-top: 24px; }
.attempt { padding: 8px 12px; border-left: 3px solid #b9c8da; margin: 8px 0; background: #f5f7fa; }
</style>
