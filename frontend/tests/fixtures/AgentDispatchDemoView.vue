<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { getDemoContext, runDispatchDemo, type Scene, type DemoContext, type DemoResult } from '@/api/agent-dispatch-demo'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const scene = ref<Scene>('normal')
const date = ref('2026-11-10')
const mode = ref<'offline' | 'real'>('offline')
const inject = ref(false)
const context = ref<DemoContext | null>(null)
const result = ref<DemoResult | null>(null)
const loading = ref(false)
const running = ref(false)
const error = ref('')
const realEnabled = ref(false)
let epoch = 0
function message(e: unknown) { return (e as { message?: string })?.message || '请求失败，请检查本地服务后重试' }
async function refresh() {
  const id = ++epoch
  context.value = null; result.value = null; error.value = ''; loading.value = true
  try {
    const response = await getDemoContext(scene.value, date.value)
    if (id === epoch) { context.value = response.data.context; realEnabled.value = response.data.real_enabled }
  } catch (e) { if (id === epoch) error.value = message(e) }
  finally { if (id === epoch) loading.value = false }
}
async function start() {
  if (running.value || !auth.canOperate || !context.value) return
  const id = ++epoch
  running.value = true; result.value = null; error.value = ''
  try {
    let authorized = false
    if (mode.value === 'real') {
      await ElMessageBox.confirm('仅发送页面所示匿名场景到已配置模型，会消耗额度；授权本次预算内调用吗？', '真实模型费用确认', { type: 'warning' })
      authorized = true
    }
    if (id !== epoch) return
    const response = await runDispatchDemo({ scene: scene.value, delivery_date: date.value, mode: mode.value,
      inject_violation: mode.value === 'offline' && scene.value !== 'normal' && inject.value, authorize_external: authorized })
    if (id === epoch) result.value = response.data
  } catch (e) { if (id === epoch && e !== 'cancel' && e !== 'close') error.value = message(e) }
  finally { if (id === epoch) running.value = false }
}
onMounted(refresh)
onBeforeUnmount(() => { epoch++ })
</script>

<template>
  <section class="demo-page">
    <h1>Agent 智能派车 · 影子演示</h1>
    <p><router-link to="/agent-dispatch/business">切换至真实业务影子模式</router-link></p>
    <el-alert title="匿名内存场景：不读取现场需求、不保存、不发布、不修改业务状态" type="info" :closable="false" />
    <el-card class="controls">
      <el-select v-model="scene" :disabled="running" @change="refresh"><el-option label="A 常规合法派车" value="normal" /><el-option label="B 超重无法分配" value="overweight" /><el-option label="C 地形合法替代" value="terrain" /></el-select>
      <el-date-picker v-model="date" type="date" value-format="YYYY-MM-DD" :clearable="false" :disabled="running" @change="refresh" />
      <el-select v-model="mode" :disabled="running"><el-option label="离线演示（非 LLM）" value="offline" /><el-option label="真实模型（需费用确认）" value="real" :disabled="!realEnabled" /></el-select>
      <el-checkbox v-model="inject" :disabled="running || mode !== 'offline' || scene === 'normal'">离线注入测试：预设违规与修正</el-checkbox>
      <el-button :disabled="running" @click="refresh">刷新场景</el-button>
      <el-button type="primary" :loading="running" :disabled="!context || loading || !auth.canOperate" @click="start">开始 Agent 智能派车</el-button>
    </el-card>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-card v-if="loading"><p>正在读取匿名场景上下文……</p></el-card>
    <el-card v-loading="loading" v-if="context">
      <h2>{{ context.delivery_date }} · {{ context.demands.length }} 个需求 · {{ context.vehicles.filter(v => v.available).length }} 辆可用车</h2>
      <el-table :data="context.demands"><el-table-column prop="id" label="匿名需求" /><el-table-column prop="quantity" label="货量 kg" /><el-table-column prop="period" label="时段（MORNING=上午）" /></el-table>
      <el-table :data="context.vehicles"><el-table-column prop="code" label="车辆" /><el-table-column prop="vehicle_type_name" label="车型" /><el-table-column prop="min_load" label="最低货量 kg" /><el-table-column prop="max_load" label="最大货量 kg" /></el-table>
      <p v-for="route in context.routes" :key="route.id">线路 {{ route.id }}：{{ route.name }} / {{ route.terrain_name }}；地形许可车型 ID：{{ context.terrain_permissions.filter(p => p[1] === route.terrain_id).map(p => p[0]).join('、') }}</p>
      <p>模式：{{ mode === 'offline' ? '离线固定候选，非模型推理' : '真实模型，点击后需单独确认' }}；没有保存或发布入口。</p>
    </el-card>
    <el-card v-if="running"><p>LangGraph 规划中，后端完成后返回实际校验轨迹；此处不模拟推理过程。</p></el-card>
    <el-card v-if="result">
      <h2>{{ result.result.status }} · {{ result.result.reason_code }}</h2>
      <el-tag>{{ result.mode === 'offline' ? (result.injection ? '离线注入测试' : '离线演示') : '实时 LLM 输出' }}</el-tag>
      <p>{{ result.result.message }}</p>
      <p v-if="result.result.candidate">已分配 {{ result.result.candidate.trips.reduce((n, t) => n + t.demand_ids.length, 0) }} 个需求；未分配 {{ result.result.candidate.unassigned.length }} 个需求。校验合法不代表所有需求都已分配。</p>
      <p>耗时 {{ result.result.elapsed_ms.toFixed(1) }} ms；生成 {{ result.result.generation_count }} 次；修正 {{ result.result.revision_count }} 次；Token {{ result.result.token_usage?.total_tokens ?? (result.mode === 'offline' ? '离线无模型调用' : '供应商未报告') }}</p>
      <p v-if="result.mode === 'real'">估算费用 {{ result.result.estimated_cost ?? '未知' }} {{ result.result.cost_currency ?? '' }}（不是账单实际费用）</p>
      <p>匿名内存快照核验 {{ result.result.freshness_checked ? '已执行' : '未执行' }}；过期 {{ result.result.stale_context ? '是，不可采纳' : '否' }}；运行 {{ result.result.run_id }}（非数据库审计记录）</p>
      <p>{{ result.result.candidate?.planning_explanation }}</p>
      <el-table :data="result.result.candidate?.trips ?? []"><el-table-column prop="vehicle_id" label="车辆" /><el-table-column prop="driver_id" label="匿名司机" /><el-table-column prop="demand_ids" label="需求" /><el-table-column prop="route_id" label="线路" /><el-table-column prop="trip_no" label="趟次" /></el-table>
      <el-table :data="result.result.candidate?.unassigned ?? []"><el-table-column prop="demand_id" label="未分配需求" /><el-table-column prop="explanation" label="原因" /></el-table>
      <div v-for="attempt in result.result.attempts" :key="attempt.generation" class="attempt">
        <h3>候选 {{ attempt.generation }}：{{ attempt.validation.is_valid ? '校验合法' : '校验拒绝' }}</h3>
        <el-table :data="attempt.validation.violations"><el-table-column prop="violation_code" label="错误码" /><el-table-column prop="message" label="确定性反馈" /></el-table>
        <el-collapse><el-collapse-item title="查看该次实际候选 JSON"><pre>{{ JSON.stringify(attempt.candidate, null, 2) }}</pre></el-collapse-item></el-collapse>
      </div>
    </el-card>
    <el-empty v-if="!loading && !running && !result && !error" description="选择场景后开始；页面刷新不会恢复未持久化的候选" />
  </section>
</template>
<style scoped>
.demo-page { display:grid;gap:18px;max-width:1200px;margin:auto } .controls :deep(.el-card__body) { display:flex;gap:12px;flex-wrap:wrap;align-items:center } .attempt { margin-top:20px;border-top:1px solid #e5eaf0 } pre { white-space:pre-wrap;overflow-wrap:anywhere } h1 { color:#17365c } @media(max-width:700px){.controls :deep(.el-select),.controls :deep(.el-date-editor){width:100%}}
</style>
