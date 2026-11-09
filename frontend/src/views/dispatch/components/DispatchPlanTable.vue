<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { planRef } from '@/utils/businessLabels'

import { getDispatchPlan, listDispatchPlans } from '@/api/dispatch-plans'
import type {
  DispatchPlanListItem,
  DispatchPlanStatus,
} from '@/types/dispatch-plan'

const props = withDefaults(
  defineProps<{
    deliveryDate: string
    refreshToken?: number
    showRefresh?: boolean
  }>(),
  {
    refreshToken: 0,
    showRefresh: true,
  },
)

const loading = ref(false)
const plans = ref<DispatchPlanListItem[]>([])
const router = useRouter()

const statusMeta: Record<DispatchPlanStatus, { label: string; type: 'warning' | 'success' | 'info' }> = {
  DRAFT: { label: '草稿', type: 'warning' },
  PUBLISHED: { label: '已发布', type: 'success' },
  CANCELLED: { label: '已取消', type: 'info' },
}

function getStatusMeta(status: DispatchPlanStatus) {
  return statusMeta[status]
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

function openDetail(planId: number) {
  router.push({ name: 'dispatch-plan-detail', params: { planId } })
}

async function loadPlans() {
  if (!props.deliveryDate) return
  loading.value = true
  try {
    const response = await listDispatchPlans({
      delivery_date: props.deliveryDate,
      offset: 0,
      limit: 100,
    })
    const details = await Promise.all(
      response.data.map(async (summary) => (await getDispatchPlan(summary.id)).data),
    )
    const detailById = new Map(details.map((detail) => [detail.id, detail]))
    plans.value = response.data.map((summary) => {
      const detail = detailById.get(summary.id)
      const assignedDemandIds = new Set(
        detail?.orders.flatMap((order) =>
          order.details.map((item) => item.delivery_demand_id),
        ) ?? [],
      )
      return {
        ...summary,
        order_count: detail?.orders.length ?? 0,
        assigned_demand_count: assignedDemandIds.size,
        unassigned_demand_count: detail?.unassigned_demands.length ?? 0,
      }
    })
  } catch {
    // Axios interceptor displays backend errors.
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.deliveryDate, props.refreshToken],
  loadPlans,
  { immediate: true },
)

defineExpose({ reload: loadPlans })
</script>

<template>
  <el-card class="plan-table-card" shadow="never">
    <template #header>
      <div class="card-header">
        <div>
          <strong>{{ deliveryDate }} 方案版本</strong>
          <span>共 {{ plans.length }} 个历史版本</span>
        </div>
        <el-button v-if="showRefresh" :icon="Refresh" :loading="loading" @click="loadPlans">刷新</el-button>
      </div>
    </template>

    <el-table v-loading="loading" :data="plans" row-key="id" stripe>
      <template #empty>
        <el-empty description="当天尚未生成派车方案" :image-size="92" />
      </template>
      <el-table-column label="方案编号" min-width="220"><template #default="{row}">{{ planRef(row.delivery_date,row.version) }}</template></el-table-column>
      <el-table-column label="版本" width="110" align="center">
        <template #default="{ row }"><span class="version-badge">V{{ row.version }}</span></template>
      </el-table-column>
      <el-table-column label="状态" width="120" align="center">
        <template #default="{ row }">
          <el-tag :type="getStatusMeta(row.status).type" effect="light">
            {{ getStatusMeta(row.status).label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="生成时间" min-width="205">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="order_count" label="订单数量" min-width="130" align="center" />
      <el-table-column prop="assigned_demand_count" label="已分配需求" min-width="140" align="center">
        <template #default="{ row }"><strong class="count-success">{{ row.assigned_demand_count }}</strong></template>
      </el-table-column>
      <el-table-column prop="unassigned_demand_count" label="未分配需求" min-width="140" align="center">
        <template #default="{ row }">
          <strong :class="row.unassigned_demand_count ? 'count-danger' : 'count-muted'">
            {{ row.unassigned_demand_count }}
          </strong>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110" align="center" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row.id)">查看详情</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.plan-table-card { border-color: #e4eaf2; border-radius: 14px; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.card-header > div { display: flex; align-items: baseline; gap: 12px; }
.card-header strong { color: #172b4d; font-size: 16px; }
.card-header span { color: #8993a4; font-size: 12px; }
.version-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 50px; height: 28px; color: #1f6fd1; font-weight: 700; background: #edf5ff; border-radius: 7px; }
.count-success { color: #22a06b; }
.count-danger { color: #d64545; }
.count-muted { color: #8993a4; }
</style>
