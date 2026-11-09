<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
defineProps<{ planId?: number }>()
const auth = useAuthStore()
const actions = computed(() => [
  { label: auth.canOperate ? '创建 / 查看需求' : '查看配送需求', path: '/operations/delivery-demands', text: '按日期管理门店货量' },
  ...(auth.canOperate ? [{ label: '自动派车', path: '/dispatch/auto', text: '生成新的草稿方案' }] : []),
  { label: '派车方案', path: '/dispatch/plans', text: '版本与配送任务' },
  { label: '每日异常', path: '/dispatch/exceptions', text: '复核当日业务异常' },
  { label: 'Agent 智能助手', path: '/agent', text: '业务查询与知识检索' },
])
</script>
<template>
  <nav class="quick-actions" aria-label="常用功能"><RouterLink v-for="action in actions" :key="action.path" :to="action.path"><strong>{{ action.label }} <span>↗</span></strong><small>{{ action.text }}</small></RouterLink><RouterLink v-if="planId" :to="`/dispatch/plans/${planId}`"><strong>物流地图 <span>↗</span></strong><small>当前方案详情中的配送路线</small></RouterLink><div v-else class="unavailable"><strong>物流地图</strong><small>参考方案有门店坐标后可查看路线</small></div></nav>
</template>
<style scoped>
.quick-actions { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; } a,.unavailable { padding:15px; border:1px solid #e5ebf3; border-radius:10px; text-decoration:none; color:#172b4d; } a:hover { border-color:#2f80ed; background:#f5f9ff; } strong { display:flex; justify-content:space-between; gap:8px; font-size:13px; } span { color:#2f80ed; } small { display:block; margin-top:7px; color:#8592a6; font-size:11px; } .unavailable { color:#94a3b8; background:#f8fafc; }
</style>
