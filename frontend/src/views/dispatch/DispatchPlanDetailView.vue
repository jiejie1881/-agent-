<script setup lang="ts">
import {
  ArrowLeft,
  Calendar,
  CircleCheck,
  Clock,
  Close,
  Location,
  OfficeBuilding,
  Promotion,
  Tickets,
  Van,
  VideoPlay,
  Warning,
} from '@element-plus/icons-vue'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  cancelDispatchPlan,
  completeDispatchOrder,
  getDispatchPlan,
  moveDispatchDemand,
  publishDispatchPlan,
  startDispatchOrder,
} from '@/api/dispatch-plans'
import type { ApiError, ApiErrorIssue } from '@/api/http'
import type {
  DispatchPlanDetail,
  DispatchPlanStatus,
  PersistedDispatchOrder,
} from '@/types/dispatch-plan'
import type { DeliveryDemandStatus } from '@/types/delivery-demand'
import { latestQualityReport } from '@/api/ai-operations'
import type { QualityReport } from '@/types/ai-operations'
import { dimensionLabels } from '@/views/dispatch/qualityHelpers'
import { businessRef, planRef, typeLabel } from '@/utils/businessLabels'
import { useAuthStore } from '@/stores/auth'
import DispatchRouteMap from '@/views/dispatch/components/DispatchRouteMap.vue'
import DeliveryReceiptPanel from '@/views/dispatch/components/DeliveryReceiptPanel.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const moving = ref(false)
const publishing = ref(false)
const cancelling = ref(false)
const actionLoadingOrderId = ref<number | null>(null)
const plan = ref<DispatchPlanDetail | null>(null)
const qualitySnapshot = ref<QualityReport | null>(null)
const qualityError = ref('')
const selectedDemand = ref('')
const selectedTargetOrderId = ref<number>()
const issueDialogVisible = ref(false)
const issueDialogTitle = ref('业务校验未通过')
const validationIssues = ref<ApiErrorIssue[]>([])

const planId = computed(() => Number(route.params.planId))

const statusMeta: Record<
  DispatchPlanStatus,
  {
    label: string
    tagType: 'warning' | 'success' | 'info'
    className: string
    message: string
  }
> = {
  DRAFT: {
    label: '草稿方案',
    tagType: 'warning',
    className: 'is-draft',
    message: '该方案尚未发布，可进行人工调整、发布或取消。',
  },
  PUBLISHED: {
    label: '已发布方案',
    tagType: 'success',
    className: 'is-published',
    message: '该方案已正式发布；各车辆任务可根据配送需求状态开始或完成配送。',
  },
  CANCELLED: {
    label: '已取消方案',
    tagType: 'info',
    className: 'is-cancelled',
    message: '该方案已经取消，仅作为历史版本保留。',
  },
}

const currentStatus = computed(() =>
  plan.value ? statusMeta[plan.value.status] : statusMeta.DRAFT,
)

const assignedDemandCount = computed(() => {
  const ids = new Set(
    plan.value?.orders.flatMap((order) =>
      order.details.map((detail) => detail.delivery_demand_id),
    ) ?? [],
  )
  return ids.size
})

const demandChoices = computed(() =>
  plan.value?.orders.flatMap((order) =>
    order.details.map((detail) => ({
      value: `${order.id}:${detail.delivery_demand_id}`,
      orderId: order.id,
      demandId: detail.delivery_demand_id,
      label: `${detail.store_name}（${formatQuantity(detail.quantity)}）`,
      source: orderTitle(order),
    })),
  ) ?? [],
)

const selectedDemandChoice = computed(() =>
  demandChoices.value.find((choice) => choice.value === selectedDemand.value),
)

const targetOrderChoices = computed(() =>
  plan.value?.orders.filter(
    (order) => order.id !== selectedDemandChoice.value?.orderId,
  ) ?? [],
)

const canMove = computed(
  () => Boolean(selectedDemandChoice.value && selectedTargetOrderId.value),
)

const anyMutationPending = computed(
  () => moving.value || publishing.value || cancelling.value || actionLoadingOrderId.value !== null,
)

type OrderExecutionStatus = DeliveryDemandStatus | 'MIXED' | 'EMPTY'
const executionStatusMeta: Record<OrderExecutionStatus, { label: string; type: 'success' | 'warning' | 'info' | 'primary' | 'danger' }> = {
  PENDING: { label: '待派车', type: 'info' },
  PLANNED: { label: '已规划', type: 'warning' },
  PUBLISHED: { label: '待开始配送', type: 'primary' },
  DELIVERING: { label: '配送中', type: 'warning' },
  COMPLETED: { label: '已完成', type: 'success' },
  CANCELLED: { label: '已取消', type: 'info' },
  MIXED: { label: '状态不一致', type: 'danger' },
  EMPTY: { label: '无需求', type: 'info' },
}

function orderExecutionStatus(order: PersistedDispatchOrder): OrderExecutionStatus {
  if (!order.details.length) return 'EMPTY'
  const statuses = new Set(order.details.map((detail) => detail.status))
  return statuses.size === 1 ? order.details[0].status : 'MIXED'
}

function periodLabel(period: 'MORNING' | 'AFTERNOON') {
  return period === 'MORNING' ? '上午' : '下午'
}

function formatQuantity(value: string) {
  return Number(value).toFixed(2)
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function orderTitle(order: PersistedDispatchOrder) {
  return `${order.vehicle.plate_number} · ${periodLabel(order.period)}第 ${order.trip_no} 趟`
}

async function loadPlan() {
  if (!Number.isInteger(planId.value) || planId.value <= 0) {
    router.replace({ name: 'dispatch-plans' })
    return
  }
  loading.value = true
  try {
    plan.value = (await getDispatchPlan(planId.value)).data
    qualitySnapshot.value = null; qualityError.value = ''
    try { qualitySnapshot.value = (await latestQualityReport(planId.value)).data }
    catch { qualityError.value = '质量报告加载失败，不影响方案详情；请到报告页重试。' }
  } catch {
    plan.value = null
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push({
    name: 'dispatch-plans',
    query: plan.value ? { date: plan.value.delivery_date } : {},
  })
}

function showBusinessIssues(error: ApiError, title: string) {
  issueDialogTitle.value = title
  validationIssues.value = error.issues?.length
    ? error.issues
    : [{ code: error.code ?? 'BUSINESS_ERROR', message: error.message }]
  issueDialogVisible.value = true
}

function resetAdjustmentSelection() {
  selectedDemand.value = ''
  selectedTargetOrderId.value = undefined
}

async function handleMoveDemand() {
  const demand = selectedDemandChoice.value
  const targetOrderId = selectedTargetOrderId.value
  if (!plan.value || !demand || !targetOrderId || anyMutationPending.value) return

  moving.value = true
  try {
    plan.value = (
      await moveDispatchDemand(plan.value.id, {
        delivery_demand_id: demand.demandId,
        source_order_id: demand.orderId,
        target_order_id: targetOrderId,
      })
    ).data
    resetAdjustmentSelection()
    ElMessage.success('需求已移动，方案载重已重新计算')
  } catch (error) {
    showBusinessIssues(error as ApiError, '需求移动失败')
  } finally {
    moving.value = false
  }
}

async function handlePublish() {
  if (!plan.value || anyMutationPending.value) return
  try {
    await ElMessageBox.confirm(
      `确认发布 ${plan.value.delivery_date} V${plan.value.version}？后端将执行发布前全量校验。`,
      '发布派车方案',
      { confirmButtonText: '确认发布', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }

  publishing.value = true
  try {
    await publishDispatchPlan(plan.value.id)
    await loadPlan()
    resetAdjustmentSelection()
    ElMessage.success('派车方案已发布')
  } catch (error) {
    showBusinessIssues(error as ApiError, '方案发布校验失败')
  } finally {
    publishing.value = false
  }
}

async function handleCancel() {
  if (!plan.value || anyMutationPending.value) return
  try {
    await ElMessageBox.confirm(
      `确认取消 ${plan.value.delivery_date} V${plan.value.version}？取消规则由后端状态机校验。`,
      '取消派车方案',
      { confirmButtonText: '确认取消', cancelButtonText: '返回', type: 'warning' },
    )
  } catch { return }

  cancelling.value = true
  try {
    await cancelDispatchPlan(plan.value.id)
    await loadPlan()
    resetAdjustmentSelection()
    ElMessage.success('派车方案已取消')
  } catch (error) {
    showBusinessIssues(error as ApiError, '取消方案失败')
  } finally {
    cancelling.value = false
  }
}

async function handleOrderAction(order: PersistedDispatchOrder, action: 'start' | 'complete') {
  if (!plan.value || anyMutationPending.value) return
  const actionLabel = action === 'start' ? '开始配送' : '完成配送'
  try {
    await ElMessageBox.confirm(
      `确认对任务 ${order.id}（${orderTitle(order)}）执行“${actionLabel}”吗？`,
      actionLabel,
      { confirmButtonText: `确认${actionLabel}`, cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }

  actionLoadingOrderId.value = order.id
  try {
    if (action === 'start') await startDispatchOrder(plan.value.id, order.id)
    else await completeDispatchOrder(plan.value.id, order.id)
    await loadPlan()
    ElMessage.success(`任务已${actionLabel}`)
  } catch (error) {
    showBusinessIssues(error as ApiError, `${actionLabel}失败`)
  } finally {
    actionLoadingOrderId.value = null
  }
}

onMounted(loadPlan)
</script>

<template>
  <section v-loading="loading" class="detail-page">
    <template v-if="plan">
      <div class="page-heading">
        <div class="page-heading__main">
          <el-button class="back-button" :icon="ArrowLeft" circle @click="goBack" />
          <div>
            <p class="page-heading__eyebrow">派车中心 / 方案详情</p>
            <el-button @click="router.push({ name: 'dispatch-quality', query: { planId } })">查看调度质量评分</el-button>
            <p v-if="qualitySnapshot">评分快照：{{ qualitySnapshot.total_score ?? '无法评分' }} · 等级 {{ qualitySnapshot.grade ?? '—' }} · 发布校验 {{ qualitySnapshot.publication_validation }} · {{ qualitySnapshot.generated_at }}（非实时，调整后请重新评分）</p>
            <p v-if="qualityError">{{ qualityError }}</p>
            <div class="title-row">
              <h1>{{ planRef(plan.delivery_date,plan.version) }}</h1>
              <el-tag :type="currentStatus.tagType" size="large" effect="light">
                {{ currentStatus.label }}
              </el-tag>
            </div>
            <p>方案 ID：{{ plan.id }} · 生成于 {{ formatDateTime(plan.created_at) }}</p>
          </div>
        </div>
      </div>

      <el-collapse v-if="qualitySnapshot">
        <el-collapse-item title="六维评分与扣分原因（历史快照）" name="quality">
          <el-table :data="qualitySnapshot.dimensions">
            <el-table-column label="评分维度" min-width="160">
              <template #default="{ row }">{{ dimensionLabels[row.key] ?? row.key }}</template>
            </el-table-column>
            <el-table-column label="得分 / 满分" min-width="120">
              <template #default="{ row }">{{ row.score }} / {{ row.max_score }}</template>
            </el-table-column>
            <el-table-column prop="deduction" label="扣分" width="90" />
            <el-table-column label="扣分原因" min-width="250">
              <template #default="{ row }">{{ row.deduction_reasons?.join('；') || '本项无扣分' }}</template>
            </el-table-column>
          </el-table>
          <p>此处为报告生成时的快照；当前方案操作仍以正式业务校验为准。</p>
        </el-collapse-item>
      </el-collapse>

      <div class="status-banner" :class="currentStatus.className">
        <el-icon><Warning /></el-icon>
        <span>{{ currentStatus.message }}</span>
      </div>

      <div v-if="authStore.canOperate && (plan.status === 'DRAFT' || plan.status === 'PUBLISHED')" class="plan-action-bar">
        <el-button type="danger" plain :icon="Close" :loading="cancelling" :disabled="anyMutationPending && !cancelling" @click="handleCancel">取消方案</el-button>
      </div>

      <el-card v-if="plan.status === 'DRAFT' && authStore.canOperate" class="adjustment-card" shadow="never">
        <template #header>
          <div class="adjustment-header">
            <div>
              <h2>人工调整</h2>
              <p>选择一个已分配需求和目标任务，提交后由后端重新执行全部业务规则校验。</p>
            </div>
            <el-button
              type="success"
              :icon="Promotion"
              :loading="publishing"
              :disabled="anyMutationPending && !publishing"
              @click="handlePublish"
            >
              发布方案
            </el-button>
          </div>
        </template>

        <div class="adjustment-form">
          <div class="adjustment-field">
            <label>选择需求</label>
            <el-select
              v-model="selectedDemand"
              filterable
              clearable
              placeholder="请选择需要移动的门店需求"
              @change="selectedTargetOrderId = undefined"
            >
              <el-option
                v-for="choice in demandChoices"
                :key="choice.value"
                :label="`${choice.label} · 来自 ${choice.source}`"
                :value="choice.value"
              />
            </el-select>
          </div>
          <div class="adjustment-arrow">→</div>
          <div class="adjustment-field">
            <label>选择目标任务</label>
            <el-select
              v-model="selectedTargetOrderId"
              filterable
              clearable
              :disabled="!selectedDemandChoice"
              placeholder="请选择目标车辆任务"
            >
              <el-option
                v-for="order in targetOrderChoices"
                :key="order.id"
                :label="`${orderTitle(order)} · ${order.route.name} · 载重 ${formatQuantity(order.total_load)}`"
                :value="order.id"
              />
            </el-select>
          </div>
          <el-button
            type="primary"
            :loading="moving"
            :disabled="!canMove || anyMutationPending"
            @click="handleMoveDemand"
          >
            移动需求
          </el-button>
        </div>
        <el-alert
          v-if="plan.orders.length < 2"
          class="adjustment-alert"
          type="info"
          :closable="false"
          title="当前方案不足两个车辆任务，暂时没有可选的目标任务。"
        />
      </el-card>

      <div class="summary-grid">
        <div class="summary-item">
          <el-icon><Tickets /></el-icon>
          <div><span>车辆任务</span><strong>{{ plan.orders.length }}</strong></div>
        </div>
        <div class="summary-item">
          <el-icon><OfficeBuilding /></el-icon>
          <div><span>已分配需求</span><strong>{{ assignedDemandCount }}</strong></div>
        </div>
        <div class="summary-item" :class="{ 'has-warning': plan.unassigned_demands.length }">
          <el-icon><Warning /></el-icon>
          <div><span>未分配需求</span><strong>{{ plan.unassigned_demands.length }}</strong></div>
        </div>
        <div class="summary-item">
          <el-icon><Calendar /></el-icon>
          <div><span>配送日期</span><strong class="summary-date">{{ plan.delivery_date }}</strong></div>
        </div>
      </div>

      <DispatchRouteMap v-if="plan.orders.some((order) => order.details.some((detail) => detail.store_latitude && detail.store_longitude))" :orders="plan.orders" />

      <div class="section-heading">
        <div>
          <span class="section-step">01</span>
          <div><h2>车辆任务 / Trip</h2><p>方案 → 车辆任务 → 线路 → 门店需求</p></div>
        </div>
      </div>

      <div v-if="plan.orders.length" class="order-list">
        <el-card v-for="order in plan.orders" :key="order.id" class="order-card" shadow="never">
          <template #header>
            <div class="order-header">
              <div class="order-identity">
                <div class="vehicle-icon"><Van /></div>
                <div>
                  <h3>{{ orderTitle(order) }}</h3>
                  <p>{{ businessRef('TASK',order.id,plan.delivery_date) }} · 内部ID {{ order.id }}</p>
                </div>
              </div>
              <div class="order-tags">
                <el-tag :type="executionStatusMeta[orderExecutionStatus(order)].type">
                  {{ executionStatusMeta[orderExecutionStatus(order)].label }}
                </el-tag>
                <el-tag :type="order.period === 'MORNING' ? 'warning' : 'primary'" effect="plain">
                  {{ order.period }} / {{ periodLabel(order.period) }}
                </el-tag>
                <el-tag effect="plain">Trip {{ order.trip_no }}</el-tag>
              </div>
            </div>
          </template>

          <div v-if="plan.status === 'PUBLISHED'" class="execution-bar">
            <div>
              <el-icon><Clock /></el-icon>
              <span>任务状态：{{ executionStatusMeta[orderExecutionStatus(order)].label }}</span>
            </div>
            <div v-if="authStore.canOperate">
              <el-button
                v-if="orderExecutionStatus(order) === 'PUBLISHED'"
                type="primary"
                :icon="VideoPlay"
                :loading="actionLoadingOrderId === order.id"
                :disabled="anyMutationPending && actionLoadingOrderId !== order.id"
                @click="handleOrderAction(order, 'start')"
              >开始配送</el-button>
              <el-button
                v-else-if="orderExecutionStatus(order) === 'DELIVERING'"
                type="success"
                :icon="CircleCheck"
                :loading="actionLoadingOrderId === order.id"
                :disabled="anyMutationPending && actionLoadingOrderId !== order.id"
                @click="handleOrderAction(order, 'complete')"
              >完成配送</el-button>
              <span v-else-if="orderExecutionStatus(order) === 'COMPLETED'" class="completed-text"><el-icon><CircleCheck /></el-icon>该任务已完成</span>
              <span v-else-if="orderExecutionStatus(order) === 'MIXED'" class="mixed-text">任务内需求状态不一致，已禁用操作</span>
            </div>
          </div>

          <div class="order-facts">
            <div><span>实际司机</span><strong>{{ order.driver_name || '姓名未填写' }}</strong><small>{{ businessRef('DRV',order.actual_driver_id) }} · 任务执行人快照</small></div>
            <div><span>车辆</span><strong>{{ order.vehicle.plate_number }}</strong><small>{{ order.vehicle.code }}</small></div>
            <div><span>车型</span><strong>{{ typeLabel(order.vehicle.vehicle_type_code,order.vehicle.vehicle_type_name) }}</strong><small>{{ order.vehicle.vehicle_type_code }}</small></div>
            <div><span>线路</span><strong>{{ order.route.name }}</strong><small>{{ order.route.code }}</small></div>
            <div><span>总载重</span><strong class="load-value">{{ formatQuantity(order.total_load) }}</strong><small>本趟明细合计</small></div>
          </div>

          <div class="route-strip">
            <el-icon><Location /></el-icon>
            <span class="route-strip__label">{{ order.route.name }}</span>
            <span class="route-strip__line" />
            <span>{{ order.details.length }} 个门店需求</span>
          </div>

          <el-table :data="order.details" row-key="id" class="detail-table">
            <template #empty><el-empty description="该任务没有门店需求" :image-size="68" /></template>
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column label="门店" min-width="230">
              <template #default="{ row }">
                <div class="store-name">{{ row.store_name }}</div>
                <div class="store-code">{{ row.store_code }}</div>
              </template>
            </el-table-column>
            <el-table-column label="需求编号" min-width="190"><template #default="{row}">{{ businessRef('DEM',row.delivery_demand_id,plan.delivery_date) }}</template></el-table-column>
          <el-table-column label="优先级" min-width="100"><template #default="{ row }">{{ row.priority === 'URGENT' ? '加急' : row.priority === 'HIGH' ? '高' : '普通' }}</template></el-table-column>
            <el-table-column label="执行状态" min-width="130" align="center">
              <template #default="{ row }"><el-tag :type="executionStatusMeta[row.status as DeliveryDemandStatus].type" size="small">{{ executionStatusMeta[row.status as DeliveryDemandStatus].label }}</el-tag></template>
            </el-table-column>
            <el-table-column label="分配货量" min-width="140" align="right">
              <template #default="{ row }"><strong>{{ formatQuantity(row.quantity) }}</strong></template>
            </el-table-column>
          </el-table>
          <DeliveryReceiptPanel :stops="order.details" />
        </el-card>
      </div>
      <el-empty v-else description="该方案没有车辆任务" />

      <div class="section-heading unassigned-heading">
        <div>
          <span class="section-step is-warning">02</span>
          <div><h2>未分配需求</h2><p>未能组成合法车次的需求及后端返回原因</p></div>
        </div>
      </div>

      <el-card class="unassigned-card" shadow="never">
        <el-table v-if="plan.unassigned_demands.length" :data="plan.unassigned_demands" row-key="id" stripe>
          <el-table-column label="门店" min-width="210">
            <template #default="{ row }">
              <div class="store-name">{{ row.store_name }}</div>
              <div class="store-code">{{ row.store_code }}</div>
            </template>
          </el-table-column>
          <el-table-column label="时段" width="110" align="center">
            <template #default="{ row }">{{ row.period }} / {{ periodLabel(row.period) }}</template>
          </el-table-column>
          <el-table-column label="货量" width="130" align="right">
            <template #default="{ row }"><strong>{{ formatQuantity(row.quantity) }}</strong></template>
          </el-table-column>
          <el-table-column label="优先级" min-width="100"><template #default="{ row }">{{ row.priority === 'URGENT' ? '加急' : row.priority === 'HIGH' ? '高' : '普通' }}</template></el-table-column>
          <el-table-column label="未分配原因" min-width="320">
            <template #default="{ row }">
              <div class="reason-list">
                <el-tag v-for="reason in row.reasons" :key="reason" type="danger" effect="plain">{{ reason }}</el-tag>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="所有需求均已分配" :image-size="84" />
      </el-card>
    </template>

    <el-empty v-else-if="!loading" description="未找到派车方案">
      <el-button type="primary" @click="goBack">返回方案列表</el-button>
    </el-empty>

    <el-dialog v-model="issueDialogVisible" :title="issueDialogTitle" width="620px">
      <p class="issue-summary">后端共返回 {{ validationIssues.length }} 个问题，本次操作未生效：</p>
      <div class="issue-list">
        <div v-for="(issue, index) in validationIssues" :key="`${issue.code}-${index}`" class="issue-item">
          <el-tag type="danger" effect="plain">{{ issue.code }}</el-tag>
          <div>
            <strong>{{ issue.message }}</strong>
            <small v-if="issue.order_id || issue.delivery_demand_id">
              <span v-if="issue.order_id">任务 ID：{{ issue.order_id }}</span>
              <span v-if="issue.delivery_demand_id">需求 ID：{{ issue.delivery_demand_id }}</span>
            </small>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="issueDialogVisible = false">我知道了</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.detail-page { min-height: 520px; max-width: 1450px; margin: 0 auto; }
.page-heading { margin-bottom: 18px; }
.page-heading__main { display: flex; align-items: flex-start; gap: 13px; }
.back-button { margin-top: 4px; }
.page-heading__eyebrow { margin: 0 0 7px; color: #2f80ed; font-size: 13px; font-weight: 600; }
.title-row { display: flex; align-items: center; gap: 12px; }
.title-row h1 { margin: 0; color: #172b4d; font-size: 28px; }
.page-heading p:not(.page-heading__eyebrow) { margin: 8px 0 0; color: #6b778c; }
.status-banner { display: flex; align-items: center; gap: 9px; margin-bottom: 16px; padding: 12px 15px; font-size: 13px; border: 1px solid; border-radius: 10px; }
.status-banner.is-draft { color: #8a5b00; background: #fff9e8; border-color: #f4d58d; }
.status-banner.is-published { color: #166744; background: #edf9f3; border-color: #a9dfc7; }
.status-banner.is-cancelled { color: #596579; background: #f3f5f8; border-color: #d7dee8; }
.plan-action-bar { display: flex; justify-content: flex-end; margin: -4px 0 16px; }
.adjustment-card { margin-bottom: 16px; border-color: #cfe0f5; border-radius: 14px; }
.adjustment-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.adjustment-header h2 { margin: 0; color: #172b4d; font-size: 18px; }
.adjustment-header p { margin: 5px 0 0; color: #7a869a; font-size: 12px; }
.adjustment-form { display: grid; grid-template-columns: minmax(260px, 1fr) 28px minmax(260px, 1fr) auto; align-items: end; gap: 12px; }
.adjustment-field label { display: block; margin-bottom: 7px; color: #42526e; font-size: 13px; font-weight: 600; }
.adjustment-field .el-select { width: 100%; }
.adjustment-arrow { padding-bottom: 8px; color: #2f80ed; font-size: 20px; text-align: center; }
.adjustment-alert { margin-top: 14px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 26px; }
.summary-item { display: flex; align-items: center; gap: 13px; padding: 17px 18px; background: #fff; border: 1px solid #e4eaf2; border-radius: 12px; }
.summary-item > .el-icon { width: 40px; height: 40px; color: #2f80ed; font-size: 21px; background: #edf5ff; border-radius: 10px; }
.summary-item span { display: block; color: #7a869a; font-size: 12px; }
.summary-item strong { display: block; margin-top: 4px; color: #172b4d; font-size: 22px; }
.summary-item strong.summary-date { font-size: 16px; }
.summary-item.has-warning strong { color: #d64545; }
.section-heading { margin: 24px 0 13px; }
.section-heading > div { display: flex; align-items: center; gap: 11px; }
.section-step { display: grid; width: 36px; height: 36px; color: #fff; font-weight: 700; background: #2f80ed; border-radius: 10px; place-items: center; }
.section-step.is-warning { background: #d97706; }
.section-heading h2 { margin: 0; color: #172b4d; font-size: 18px; }
.section-heading p { margin: 3px 0 0; color: #8993a4; font-size: 12px; }
.order-list { display: flex; flex-direction: column; gap: 16px; }
.order-card, .unassigned-card { border-color: #e4eaf2; border-radius: 14px; }
.order-header { display: flex; align-items: center; justify-content: space-between; }
.order-identity, .order-tags { display: flex; align-items: center; gap: 10px; }
.vehicle-icon { display: grid; width: 42px; height: 42px; color: #fff; background: #2f80ed; border-radius: 11px; place-items: center; }
.vehicle-icon :deep(svg) { width: 24px; }
.order-identity h3 { margin: 0; color: #172b4d; font-size: 16px; }
.order-identity p { margin: 4px 0 0; color: #8993a4; font-size: 11px; }
.order-facts { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; margin-bottom: 18px; overflow: hidden; background: #e7ebf1; border: 1px solid #e7ebf1; border-radius: 9px; }
.order-facts > div { padding: 13px 15px; background: #f8fafc; }
.order-facts span, .order-facts small { display: block; color: #8993a4; font-size: 11px; }
.order-facts strong { display: block; margin: 5px 0 3px; color: #172b4d; }
.order-facts strong.load-value { color: #1f6fd1; font-size: 18px; }
.execution-bar { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px; padding: 11px 13px; background: #f7f9fc; border: 1px solid #e5eaf1; border-radius: 9px; }
.execution-bar > div { display: flex; align-items: center; gap: 8px; color: #52627a; font-size: 13px; }
.completed-text { display: inline-flex; align-items: center; gap: 5px; color: #22a06b; font-weight: 600; }
.mixed-text { color: #d64545; font-weight: 600; }
.route-strip { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; color: #6b778c; font-size: 12px; }
.route-strip > .el-icon { color: #2f80ed; }
.route-strip__label { color: #172b4d; font-weight: 600; }
.route-strip__line { flex: 1; height: 1px; background: #e6ebf2; }
.detail-table { border: 1px solid #edf0f4; border-radius: 8px; }
.store-name { color: #172b4d; font-weight: 600; }
.store-code { margin-top: 3px; color: #8993a4; font-family: Consolas, monospace; font-size: 11px; }
.unassigned-heading { margin-top: 30px; }
.reason-list { display: flex; flex-wrap: wrap; gap: 5px; }
.issue-summary { margin: 0 0 12px; color: #6b778c; }
.issue-list { display: flex; max-height: 420px; overflow-y: auto; flex-direction: column; gap: 10px; }
.issue-item { display: flex; align-items: flex-start; gap: 10px; padding: 12px; background: #fff7f7; border: 1px solid #f5cccc; border-radius: 8px; }
.issue-item strong { display: block; color: #4b2630; font-size: 13px; font-weight: 500; }
.issue-item small { display: flex; gap: 12px; margin-top: 5px; color: #8993a4; }
@media (max-width: 900px) {
  .adjustment-form { grid-template-columns: 1fr; }
  .adjustment-arrow { display: none; }
  .summary-grid, .order-facts { grid-template-columns: repeat(2, 1fr); }
}
</style>
