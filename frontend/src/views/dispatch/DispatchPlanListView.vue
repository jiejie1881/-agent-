<script setup lang="ts">
import { Calendar, Promotion } from '@element-plus/icons-vue'
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

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

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const selectedDate = ref(localDate())

function syncQuery() {
  router.replace({ query: { ...route.query, date: selectedDate.value } })
}

function goToAutoDispatch() {
  router.push({ name: 'auto-dispatch' })
}

onMounted(() => {
  const queryDate = typeof route.query.date === 'string' ? route.query.date : ''
  if (/^\d{4}-\d{2}-\d{2}$/.test(queryDate)) selectedDate.value = queryDate
})
</script>

<template>
  <section class="dispatch-page">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">派车中心</p>
        <h1>方案列表</h1>
        <p>按配送日期查看自动派车生成的全部历史版本及分配统计。</p>
      </div>
      <el-button v-if="authStore.canOperate" type="primary" :icon="Promotion" @click="goToAutoDispatch">自动派车</el-button>
    </div>

    <el-card class="date-card" shadow="never">
      <span>配送日期</span>
      <el-date-picker
        v-model="selectedDate"
        type="date"
        value-format="YYYY-MM-DD"
        :prefix-icon="Calendar"
        :clearable="false"
        @change="syncQuery"
      />
    </el-card>

    <DispatchPlanTable :delivery-date="selectedDate" />
  </section>
</template>

<style scoped>
.dispatch-page { max-width: 1450px; margin: 0 auto; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
.page-heading__eyebrow { margin: 0 0 7px; color: #2f80ed; font-size: 13px; font-weight: 600; }
.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }
.page-heading p:not(.page-heading__eyebrow) { margin: 9px 0 0; color: #6b778c; }
.date-card { margin-bottom: 18px; border-color: #e4eaf2; border-radius: 14px; }
.date-card :deep(.el-card__body) { display: flex; align-items: center; gap: 12px; }
.date-card span { color: #52627a; font-size: 13px; font-weight: 600; }
</style>
