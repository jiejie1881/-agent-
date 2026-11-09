<script setup lang="ts">
import { Edit, Lock, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { businessRef } from '@/utils/businessLabels'

import {
  createDeliveryDemand,
  listDeliveryDemands,
  updateDeliveryDemand,
} from '@/api/delivery-demands'
import { listStores } from '@/api/stores'
import type {
  DeliveryDemand,
  DeliveryDemandPayload,
  DeliveryDemandStatus,
  DeliveryPeriod,
} from '@/types/delivery-demand'
import type { Store } from '@/types/store'
import DeliveryDemandFormDialog from '@/views/operations/components/DeliveryDemandFormDialog.vue'
import AIDemandDialog from '@/views/operations/components/AIDemandDialog.vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

function localDate(): string {
  const value = new Date()
  return [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, '0'),
    String(value.getDate()).padStart(2, '0'),
  ].join('-')
}

const selectedDate = ref(localDate())
const selectedPeriod = ref<DeliveryPeriod | ''>('')
const selectedStatus = ref<DeliveryDemandStatus | ''>('')
const loading = ref(false)
const submitting = ref(false)
const demands = ref<DeliveryDemand[]>([])
const stores = ref<Store[]>([])
const dialogVisible = ref(false)
const aiDialogVisible = ref(false)
async function aiCreated(dates: string[]) {
  if (dates.length === 1 && dates[0]) selectedDate.value = dates[0]
  await loadData()
  if (dates.length > 1) ElMessage.info(`已创建跨日期需求：${dates.join('、')}，切换对应日期查看`)
}
const editingDemand = ref<DeliveryDemand | null>(null)

const statusMeta: Record<DeliveryDemandStatus, { label: string; type: '' | 'success' | 'warning' | 'info' | 'primary' | 'danger' }> = {
  PENDING: { label: '待派车', type: 'info' },
  PLANNED: { label: '已规划', type: 'warning' },
  PUBLISHED: { label: '已发布', type: 'primary' },
  DELIVERING: { label: '配送中', type: 'warning' },
  COMPLETED: { label: '已完成', type: 'success' },
  CANCELLED: { label: '已取消', type: 'danger' },
}

const filteredDemands = computed(() =>
  demands.value.filter(
    (item) =>
      (!selectedPeriod.value || item.period === selectedPeriod.value) &&
      (!selectedStatus.value || item.status === selectedStatus.value),
  ),
)

const totalQuantity = computed(() =>
  filteredDemands.value.reduce((total, item) => total + Number(item.quantity), 0),
)

function getStatusMeta(status: DeliveryDemandStatus) {
  return statusMeta[status]
}

async function loadData() {
  loading.value = true
  try {
    const [demandResponse, storeResponse] = await Promise.all([
      listDeliveryDemands({ date: selectedDate.value, offset: 0, limit: 100 }),
      listStores({ offset: 0, limit: 100 }),
    ])
    demands.value = demandResponse.data
    stores.value = storeResponse.data
  } catch {
    // Axios interceptor displays backend errors.
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingDemand.value = null
  dialogVisible.value = true
}

function openEdit(demand: DeliveryDemand) {
  editingDemand.value = demand
  dialogVisible.value = true
}

async function submitDemand(payload: DeliveryDemandPayload) {
  submitting.value = true
  try {
    if (editingDemand.value) {
      await updateDeliveryDemand(editingDemand.value.id, payload)
      ElMessage.success('配送需求修改成功')
    } else {
      await createDeliveryDemand(payload)
      ElMessage.success('配送需求新增成功')
    }
    dialogVisible.value = false
    await loadData()
  } catch {
    // Backend business errors are shown by the Axios interceptor.
  } finally {
    submitting.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <section class="operation-page">
    <AIDemandDialog v-model="aiDialogVisible" :date="selectedDate" @created="aiCreated" />
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">每日运营</p>
        <h1>配送需求</h1>
        <p>按配送日期维护门店上午和下午的配送货量。</p>
      </div>
      <div><el-button v-if="authStore.user?.role === 'ADMIN'" @click="aiDialogVisible = true">AI 智能录入</el-button><el-button v-if="authStore.canOperate" type="primary" :icon="Plus" @click="openCreate">新增需求</el-button></div>
    </div>

    <el-card class="filter-card" shadow="never">
      <div class="filter-row">
        <div class="filter-item">
          <span>配送日期</span>
          <el-date-picker
            v-model="selectedDate"
            type="date"
            value-format="YYYY-MM-DD"
            :clearable="false"
            @change="loadData"
          />
        </div>
        <div class="filter-item">
          <span>时段</span>
          <el-select v-model="selectedPeriod" placeholder="全部时段" clearable style="width: 150px">
            <el-option label="上午" value="MORNING" />
            <el-option label="下午" value="AFTERNOON" />
          </el-select>
        </div>
        <div class="filter-item">
          <span>状态</span>
          <el-select v-model="selectedStatus" placeholder="全部状态" clearable style="width: 150px">
            <el-option v-for="(meta, status) in statusMeta" :key="status" :label="meta.label" :value="status" />
          </el-select>
        </div>
        <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
      </div>
    </el-card>

    <div class="summary-bar">
      <span>当前显示 <strong>{{ filteredDemands.length }}</strong> 条需求</span>
      <span>货量合计 <strong>{{ totalQuantity.toFixed(2) }}</strong></span>
    </div>

    <el-card class="table-card" shadow="never">
      <el-table v-loading="loading" :data="filteredDemands" row-key="id" stripe>
        <template #empty><el-empty description="当天暂无配送需求" :image-size="92" /></template>
        <el-table-column label="需求编号" min-width="190"><template #default="{row}">{{ businessRef('DEM',row.id,row.date) }}</template></el-table-column>
        <el-table-column label="门店" min-width="210">
          <template #default="{ row }">
            <div class="primary-text">{{ row.store.name }}</div>
            <div class="secondary-text">{{ row.store.code }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="store.address" label="门店地址" min-width="230">
          <template #default="{ row }">{{ row.store.address || '—' }}</template>
        </el-table-column>
        <el-table-column label="时段" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.period === 'MORNING' ? 'warning' : 'primary'" effect="plain">
              {{ row.period === 'MORNING' ? '上午' : '下午' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="货量" width="140" align="right">
          <template #default="{ row }"><strong>{{ Number(row.quantity).toFixed(2) }}</strong></template>
        </el-table-column>
        <el-table-column label="优先级" width="100" align="center"><template #default="{ row }"><el-tag :type="row.priority === 'URGENT' ? 'danger' : row.priority === 'HIGH' ? 'warning' : 'info'">{{ row.priority === 'URGENT' ? '加急' : row.priority === 'HIGH' ? '高' : '普通' }}</el-tag></template></el-table-column>
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="getStatusMeta(row.status).type">{{ getStatusMeta(row.status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="authStore.canOperate" label="操作" width="130" align="center" fixed="right">
          <template #default="{ row }">
            <el-tooltip
              :disabled="row.core_fields_editable"
              content="后端已锁定该需求的核心字段"
              placement="top"
            >
              <span>
                <el-button
                  link
                  type="primary"
                  :icon="row.core_fields_editable ? Edit : Lock"
                  :disabled="!row.core_fields_editable"
                  @click="openEdit(row)"
                >编辑</el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <DeliveryDemandFormDialog
      v-if="authStore.canOperate"
      v-model="dialogVisible"
      :demand="editingDemand"
      :default-date="selectedDate"
      :stores="stores"
      :submitting="submitting"
      @submit="submitDemand"
    />
  </section>
</template>

<style scoped>
.operation-page { max-width: 1500px; margin: 0 auto; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
.page-heading__eyebrow { margin: 0 0 7px; color: #2f80ed; font-size: 13px; font-weight: 600; }
.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }
.page-heading p:not(.page-heading__eyebrow) { margin: 9px 0 0; color: #6b778c; }
.filter-card, .table-card { border-color: #e4eaf2; border-radius: 14px; }
.filter-row { display: flex; align-items: center; gap: 22px; }
.filter-item { display: flex; align-items: center; gap: 9px; color: #52627a; font-size: 14px; }
.summary-bar { display: flex; gap: 28px; padding: 15px 4px; color: #6b778c; font-size: 14px; }
.summary-bar strong { color: #172b4d; }
.primary-text { color: #172b4d; font-weight: 600; }
.secondary-text { margin-top: 3px; color: #8993a4; font-size: 12px; }
</style>
