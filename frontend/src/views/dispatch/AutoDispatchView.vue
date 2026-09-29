<script setup lang="ts">
import { Calendar, Promotion, Tickets } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { generateAutoDispatch } from '@/api/dispatch-plans'
import type { AutoDispatchResult } from '@/types/dispatch-plan'
import DispatchPlanTable from '@/views/dispatch/components/DispatchPlanTable.vue'
import { useAuthStore } from '@/stores/auth'

function localDate(): string {
  const value = new Date()
  return [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, '0'),
    String(value.getDate()).padStart(2, '0'),
  ].join('-')
}

const router = useRouter()
const authStore = useAuthStore()
const selectedDate = ref(localDate())
const generating = ref(false)
const latestResult = ref<AutoDispatchResult | null>(null)
const refreshToken = ref(0)

const assignedDemandCount = computed(() => {
  const ids = new Set(
    latestResult.value?.trips.flatMap((trip) =>
      trip.stores.map((store) => store.demand_id),
    ) ?? [],
  )
  return ids.size
})

async function generate() {
  generating.value = true
  try {
    const response = await generateAutoDispatch(selectedDate.value)
    latestResult.value = response.data
    refreshToken.value += 1
    ElMessage.success(`已生成 ${selectedDate.value} 的 V${response.data.version} 草稿方案`)
  } catch {
    // Axios interceptor displays backend business errors.
  } finally {
    generating.value = false
  }
}

function changeDate() {
  latestResult.value = null
}

function openPlanList() {
  router.push({ name: 'dispatch-plans', query: { date: selectedDate.value } })
}

function openLatestDetail() {
  if (!latestResult.value) return
  router.push({
    name: 'dispatch-plan-detail',
    params: { planId: latestResult.value.plan_id },
  })
}
</script>

<template>
  <section class="dispatch-page">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">派车中心</p>
        <h1>自动派车</h1>
        <p>选择配送日期，使用当前需求、出勤、线路和车型规则生成新的 DRAFT 版本。</p>
      </div>
      <el-button :icon="Tickets" @click="openPlanList">查看方案列表</el-button>
    </div>

    <el-card class="generator-card" shadow="never">
      <div class="generator-content">
        <div>
          <span class="field-label">配送日期</span>
          <el-date-picker
            v-model="selectedDate"
            type="date"
            value-format="YYYY-MM-DD"
            :prefix-icon="Calendar"
            :clearable="false"
            @change="changeDate"
          />
        </div>
        <el-button v-if="authStore.canOperate" type="primary" size="large" :icon="Promotion" :loading="generating" @click="generate">
          {{ generating ? '正在生成方案' : '开始自动派车' }}
        </el-button>
      </div>
      <p class="generator-hint">{{ authStore.canOperate ? '每次执行都会保存一个新的版本；不会覆盖已有的 DRAFT 或 PUBLISHED 方案。' : '当前账号为只读权限，可以查看历史方案。' }}</p>
    </el-card>

    <Transition name="result-slide">
      <el-card v-if="latestResult" class="result-card" shadow="never">
        <div class="result-title">
          <div class="result-version">V{{ latestResult.version }}</div>
          <div>
            <h2>派车方案已生成</h2>
            <p>方案 ID：{{ latestResult.plan_id }} · 状态：{{ latestResult.status }}</p>
          </div>
        </div>
        <div class="result-metrics">
          <div><span>订单数量</span><strong>{{ latestResult.trips.length }}</strong></div>
          <div><span>已分配需求</span><strong>{{ assignedDemandCount }}</strong></div>
          <div><span>未分配需求</span><strong :class="{ danger: latestResult.unassigned_demands.length }">{{ latestResult.unassigned_demands.length }}</strong></div>
        </div>
        <el-button type="primary" plain @click="openLatestDetail">查看详情</el-button>
      </el-card>
    </Transition>

    <DispatchPlanTable :delivery-date="selectedDate" :refresh-token="refreshToken" />
  </section>
</template>

<style scoped>
.dispatch-page { max-width: 1450px; margin: 0 auto; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
.page-heading__eyebrow { margin: 0 0 7px; color: #2f80ed; font-size: 13px; font-weight: 600; }
.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }
.page-heading p:not(.page-heading__eyebrow) { margin: 9px 0 0; color: #6b778c; }
.generator-card, .result-card { margin-bottom: 18px; border-color: #e4eaf2; border-radius: 14px; }
.generator-content { display: flex; align-items: flex-end; justify-content: space-between; }
.field-label { display: block; margin-bottom: 8px; color: #52627a; font-size: 13px; font-weight: 600; }
.generator-hint { margin: 14px 0 0; color: #8993a4; font-size: 12px; }
.result-card { background: linear-gradient(120deg, #f4f9ff, #fff); border-color: #cfe2fb; }
.result-card :deep(.el-card__body) { display: flex; align-items: center; justify-content: space-between; }
.result-title { display: flex; align-items: center; gap: 15px; }
.result-version { display: grid; width: 58px; height: 58px; color: #fff; font-size: 20px; font-weight: 700; background: #2f80ed; border-radius: 16px; place-items: center; }
.result-title h2 { margin: 0; color: #172b4d; font-size: 18px; }
.result-title p { margin: 6px 0 0; color: #6b778c; font-size: 13px; }
.result-metrics { display: flex; gap: 42px; }
.result-metrics div { text-align: center; }
.result-metrics span { display: block; color: #7a869a; font-size: 12px; }
.result-metrics strong { display: block; margin-top: 5px; color: #22a06b; font-size: 24px; }
.result-metrics strong.danger { color: #d64545; }
.result-slide-enter-active, .result-slide-leave-active { transition: all 0.2s ease; }
.result-slide-enter-from, .result-slide-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
