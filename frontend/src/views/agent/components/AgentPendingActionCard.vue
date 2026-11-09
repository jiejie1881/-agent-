<script setup lang="ts">
import { computed } from 'vue'

import type { AgentPendingAction } from '@/types/agent'

const props = defineProps<{
  action: AgentPendingAction
  loading: boolean
  canOperate: boolean
}>()

defineEmits<{
  confirm: [action: AgentPendingAction]
  cancel: [action: AgentPendingAction]
}>()

const labels: Record<string, string> = {
  move_delivery_demand: '移动配送需求',
  cancel_dispatch_plan: '取消派车方案',
}

const statusType = computed(() => ({
  PENDING: 'warning', EXECUTED: 'success', CANCELLED: 'info', EXPIRED: 'info', FAILED: 'danger', CONFIRMED: 'primary',
}[props.action.status] as 'warning' | 'success' | 'info' | 'danger' | 'primary'))

// This fingerprint is an internal consistency check, not a business field or
// an authorization decision. The backend still validates it on confirmation.
const displayData = computed(() => Object.fromEntries(
  Object.entries(props.action.display_data).filter(([key]) => key !== 'approval_fingerprint'),
))

function displayValue(value: unknown) {
  return value === null || value === undefined ? '-' : String(value)
}
</script>

<template>
  <el-card class="action-card" shadow="never" :class="{ 'is-high-risk': action.risk_level === 'HIGH' }">
    <template #header>
      <div class="action-card__header">
        <strong>待确认操作 · {{ labels[action.tool_name] ?? action.tool_name }}</strong>
        <el-tag :type="statusType" effect="dark">{{ action.status }}</el-tag>
      </div>
    </template>
    <p class="action-card__summary">{{ action.summary }}</p>
    <dl>
      <template v-for="(value, key) in displayData" :key="key">
        <dt>{{ key }}</dt><dd>{{ displayValue(value) }}</dd>
      </template>
    </dl>
    <el-alert
      :title="action.risk_message"
      :type="action.risk_level === 'HIGH' ? 'error' : 'warning'"
      :closable="false"
      show-icon
    />
    <div v-if="action.status === 'PENDING'" class="action-card__actions">
      <el-button :disabled="loading || !canOperate" @click="$emit('cancel', action)">取消</el-button>
      <el-button type="primary" :loading="loading" :disabled="!canOperate" @click="$emit('confirm', action)">
        确认执行
      </el-button>
    </div>
  </el-card>
</template>

<style scoped>
.action-card { margin: 0 0 22px 45px; border-color: #e6a23c; }
.action-card.is-high-risk { border-color: #f56c6c; }
.action-card__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.action-card__summary { margin: 0 0 14px; color: #243b5a; font-weight: 600; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 7px 14px; margin: 0 0 14px; font-size: 13px; }
dt { color: #8993a4; }
dd { margin: 0; color: #344563; overflow-wrap: anywhere; }
.action-card__actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
</style>
