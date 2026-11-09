<script setup lang="ts">
import { businessRef, planRef } from '@/utils/businessLabels'
import { Calendar, Refresh } from '@element-plus/icons-vue'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getDailyExceptionReport } from '@/api/daily-exceptions'
import { listDispatchPlans } from '@/api/dispatch-plans'
import type { DailyExceptionReport } from '@/types/daily-exception'
import type { DispatchPlanSummary } from '@/types/dispatch-plan'

const router = useRouter()
const today = new Date()
const selectedDate = ref(
  `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`,
)
const selectedPlanId = ref<number | null>(null)
const plans = ref<DispatchPlanSummary[]>([])
const report = ref<DailyExceptionReport | null>(null)
const loading = ref(false)
const errorMessage = ref('')
let requestVersion = 0

function errorText(error: unknown): string {
  return error && typeof error === 'object' && 'message' in error && typeof error.message === 'string'
    ? error.message
    : '报告加载失败，请重试'
}

function issueLabel(issue: string): string {
  const labels: Record<string, string> = {
    ATTENDANCE_MISSING: '未登记出勤',
    ATTENDANCE_UNAVAILABLE: '不可出勤',
    VEHICLE_INACTIVE: '车辆停用',
    VEHICLE_TYPE_INACTIVE: '车型停用',
  }
  return labels[issue] || issue
}

const failureLabels: Record<string, string> = {
  STORE_CLOSED: '门店关闭', REJECTED: '门店拒收', ADDRESS_ERROR: '地址错误',
  CARGO_DAMAGED: '货物损坏', OTHER: '其他',
}

async function fetchReport(version: number) {
  if (!selectedDate.value) return
  loading.value = true
  report.value = null
  errorMessage.value = ''
  try {
    const response = await getDailyExceptionReport({
      date: selectedDate.value,
      ...(selectedPlanId.value ? { plan_id: selectedPlanId.value } : {}),
      example_limit: 20,
    })
    if (version === requestVersion) report.value = response.data
  } catch (error) {
    if (version === requestVersion) errorMessage.value = errorText(error)
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

async function loadReport() {
  await fetchReport(++requestVersion)
}

async function loadDate() {
  if (!selectedDate.value) return
  const version = ++requestVersion
  selectedPlanId.value = null
  plans.value = []
  report.value = null
  errorMessage.value = ''
  loading.value = true
  try {
    const response = await listDispatchPlans({ delivery_date: selectedDate.value, limit: 100 })
    if (version === requestVersion) plans.value = response.data
  } catch {
    // The report remains independently queryable if the version list fails.
  }
  if (version === requestVersion) await fetchReport(version)
}

function openPlan() {
  const id = report.value?.reference_plan?.id
  if (id) router.push({ name: 'dispatch-plan-detail', params: { planId: id } })
}

onMounted(loadDate)
</script>

<template>
  <section class="exception-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">派车中心</p>
        <h1>每日异常工作台</h1>
        <p>按当前业务数据查看待计划需求、方案异常和配送失败记录。只读，不会修改方案。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadDate">刷新</el-button>
    </div>

    <el-card class="filter-card" shadow="never">
      <div class="filters">
        <span>配送日期</span>
        <el-date-picker v-model="selectedDate" type="date" value-format="YYYY-MM-DD" :prefix-icon="Calendar" :clearable="false" @change="loadDate" />
        <span>参考方案</span>
        <el-select v-model="selectedPlanId" placeholder="自动选择" clearable style="width: 220px" @change="loadReport">
          <el-option v-for="plan in plans" :key="plan.id" :label="`V${plan.version} · ${plan.status} · #${plan.id}`" :value="plan.id" />
        </el-select>
      </div>
    </el-card>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" class="notice" />
    <div v-loading="loading">
      <template v-if="report">
        <el-alert v-for="notice in report.notices" :key="notice" :title="notice" type="warning" :closable="false" class="notice" />
        <el-card class="reference-card" shadow="never">
          <template v-if="report.reference_plan">
            <span>参考方案：{{ planRef(report.delivery_date, report.reference_plan.version) }}</span>
            <el-tag :type="report.reference_plan.status === 'PUBLISHED' ? 'success' : 'info'">{{ report.reference_plan.status }}</el-tag>
            <el-button link type="primary" @click="openPlan">查看方案 #{{ report.reference_plan.id }}</el-button>
          </template>
          <span v-else>该日期暂无已发布或草稿方案</span>
        </el-card>

        <div class="overview">
          <el-card shadow="never"><span>方案内未分配</span><strong>{{ report.plan_unassigned.count }}</strong></el-card>
          <el-card shadow="never"><span>方案外待计划</span><strong>{{ report.pending_outside_reference_plan.count }}</strong></el-card>
          <el-card shadow="never"><span>车辆出勤异常</span><strong>{{ report.plan_vehicle_unavailable.count }}</strong></el-card>
          <el-card shadow="never"><span>配送失败停靠点</span><strong>{{ report.failed_stops.count }}</strong></el-card>
        </div>

        <div class="section-grid">
          <el-card shadow="never"><template #header>签收回单异常 <el-tag type="warning">{{ report.receipt_issues?.count ?? 0 }}</el-tag></template>
            <el-table :data="report.receipt_issues?.examples ?? []" empty-text="没有回单异常"><el-table-column prop="object_id" label="业务记录 ID" /><el-table-column prop="category" label="类别" /><el-table-column prop="store_name" label="门店" /><el-table-column prop="message" label="事实" /></el-table>
            <router-link to="/dispatch/exception-cases">登记并处理异常工单</router-link>
          </el-card>
          <el-card shadow="never"><template #header>业务状态冲突 <el-tag type="danger">{{ report.state_conflicts?.count ?? 0 }}</el-tag></template>
            <el-table :data="report.state_conflicts?.examples ?? []" empty-text="没有状态冲突"><el-table-column prop="object_id" label="停靠点 ID" /><el-table-column prop="store_name" label="门店" /><el-table-column prop="message" label="事实" /></el-table>
          </el-card>
          <el-card shadow="never">
            <template #header>方案内未分配需求 <el-tag type="danger">{{ report.plan_unassigned.count }}</el-tag></template>
            <el-table :data="report.plan_unassigned.examples" empty-text="没有未分配需求">
              <el-table-column label="需求编号" min-width="180"><template #default="{ row }">{{ businessRef('DEM', row.demand_id, report.delivery_date) }}</template></el-table-column>
              <el-table-column prop="store_name" label="门店" min-width="110" />
              <el-table-column prop="priority" label="优先级" width="100" />
              <el-table-column label="方案记录原因" min-width="180"><template #default="scope">{{ scope.row.reasons.join('；') || '未记录' }}</template></el-table-column>
            </el-table>
            <p v-if="report.plan_unassigned.truncated" class="truncation">仅显示前 20 条；完整明细请查看方案详情。</p>
          </el-card>

          <el-card shadow="never">
            <template #header>方案外待计划需求 <el-tag type="warning">{{ report.pending_outside_reference_plan.count }}</el-tag></template>
            <el-table :data="report.pending_outside_reference_plan.examples" empty-text="没有方案外待计划需求">
              <el-table-column label="需求编号" min-width="180"><template #default="{ row }">{{ businessRef('DEM', row.demand_id, report.delivery_date) }}</template></el-table-column>
              <el-table-column prop="store_name" label="门店" min-width="120" />
              <el-table-column prop="priority" label="优先级" width="100" />
              <el-table-column prop="period" label="时段" width="120" />
            </el-table>
            <p v-if="report.pending_outside_reference_plan.truncated" class="truncation">仅显示前 20 条；完整需求请查看配送需求页。</p>
          </el-card>

          <el-card shadow="never">
            <template #header>方案车辆出勤异常 <el-tag type="danger">{{ report.plan_vehicle_unavailable.count }}</el-tag></template>
            <el-table :data="report.plan_vehicle_unavailable.examples" empty-text="没有发现出勤异常">
              <el-table-column prop="vehicle_plate" label="车辆" min-width="110" />
              <el-table-column label="任务编号" min-width="180"><template #default="{ row }">{{ businessRef('TASK', row.order_id, report.delivery_date) }}</template></el-table-column>
              <el-table-column prop="period" label="时段" width="120" />
              <el-table-column prop="trip_no" label="趟次" width="70" />
              <el-table-column label="异常" min-width="170"><template #default="scope">{{ scope.row.issues.map(issueLabel).join('；') }}</template></el-table-column>
            </el-table>
            <p v-if="report.plan_vehicle_unavailable.truncated" class="truncation">仅显示前 20 条。</p>
          </el-card>

          <el-card shadow="never">
            <template #header>配送失败停靠点 <el-tag type="danger">{{ report.failed_stops.count }}</el-tag></template>
            <el-table :data="report.failed_stops.examples" empty-text="没有配送失败记录">
              <el-table-column prop="store_name" label="门店" min-width="120" />
              <el-table-column label="需求编号" min-width="180"><template #default="{ row }">{{ businessRef('DEM', row.demand_id, report.delivery_date) }}</template></el-table-column>
              <el-table-column label="任务编号" min-width="180"><template #default="{ row }">{{ businessRef('TASK', row.order_id, report.delivery_date) }}</template></el-table-column>
              <el-table-column prop="vehicle_plate" label="车辆" min-width="100" />
              <el-table-column label="实际执行司机" min-width="140"><template #default="{ row }">{{ row.actual_driver_name || '历史未记录' }}<br>{{ businessRef('DRV', row.actual_driver_id) }}</template></el-table-column>
              <el-table-column prop="arrived_at" label="到店时间" min-width="170" />
              <el-table-column label="失败原因" min-width="130">
                <template #default="{ row }"><span :title="row.failure_reason">{{ failureLabels[row.failure_reason] ?? row.failure_reason ?? '—' }}</span></template>
              </el-table-column>
            </el-table>
            <p v-if="report.failed_stops.truncated" class="truncation">仅显示前 20 条。</p>
          </el-card>
        </div>
        <p class="report-note">{{ report.note }}</p>
      </template>
      <el-empty v-else-if="!loading && !errorMessage" description="暂无报告，请选择日期后刷新" />
    </div>
  </section>
</template>

<style scoped>
.exception-page { max-width: 1450px; margin: 0 auto; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
.eyebrow { margin: 0 0 7px; color: #2f80ed; font-size: 13px; font-weight: 600; }
.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }
.page-heading p:not(.eyebrow) { margin: 9px 0 0; color: #6b778c; }
.filter-card, .reference-card { margin-bottom: 16px; border-color: #e4eaf2; border-radius: 14px; }
.filters { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; color: #52627a; font-size: 13px; font-weight: 600; }
.reference-card :deep(.el-card__body) { display: flex; align-items: center; gap: 12px; }
.notice { margin-bottom: 12px; }
.section-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.overview { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.overview :deep(.el-card__body) { display: flex; flex-direction: column; gap: 6px; color: #52627a; font-size: 13px; }
.overview strong { color: #172b4d; font-size: 23px; }
.section-grid :deep(.el-card) { border-color: #e4eaf2; border-radius: 14px; }
.section-grid :deep(.el-card__header) { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.truncation, .report-note { color: #6b778c; font-size: 12px; }
.report-note { margin-top: 16px; }
@media (max-width: 900px) { .section-grid { grid-template-columns: 1fr; } .overview { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
