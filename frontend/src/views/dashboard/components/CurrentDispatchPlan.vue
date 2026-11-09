<script setup lang="ts">
import type { DispatchPlanDetail } from '@/types/dispatch-plan'
defineProps<{ plan: DispatchPlanDetail | null; assigned: number; unassigned: number }>()
</script>
<template>
  <el-empty v-if="!plan" description="该日期暂无已发布或草稿方案" :image-size="70" />
  <template v-else>
    <div class="plan-top"><div><span>派车方案 #{{ plan.id }}</span><h3>V{{ plan.version }} <el-tag :type="plan.status === 'PUBLISHED' ? 'success' : 'warning'">{{ plan.status }}</el-tag></h3></div><el-button type="primary" plain @click="$router.push(`/dispatch/plans/${plan.id}`)">查看方案 →</el-button></div>
    <p v-if="plan.status === 'DRAFT'" class="draft-note">草稿尚未发布，仅供规划参考，不代表当前执行方案。</p>
    <div class="plan-counts"><div><strong>{{ plan.orders.length }}</strong><span>车辆任务 / 趟</span></div><div><strong>{{ assigned }}</strong><span>已分配需求 / 去重</span></div><div><strong>{{ unassigned }}</strong><span>未分配需求 / 去重</span></div></div>
    <p class="date-line">配送日期 {{ plan.delivery_date }} · 最近更新 {{ new Date(plan.updated_at).toLocaleString('zh-CN') }}</p>
  </template>
</template>
<style scoped>
.plan-top { display:flex; align-items:center; justify-content:space-between; gap:10px; } .plan-top span { color:#8592a6; font-size:12px; } h3 { color:#172b4d; font-size:30px; margin:8px 0 0; display:flex; align-items:center; gap:12px; } .plan-counts { display:grid; grid-template-columns:repeat(3,1fr); margin:24px 0; padding:18px 0; background:#f7f9fc; border-radius:10px; } .plan-counts div { text-align:center; } strong { display:block; font-size:23px; color:#172b4d; } .plan-counts span,.date-line { font-size:11px; color:#8592a6; } .plan-counts span { display:block; margin-top:7px; } .draft-note { color:#b7791f; font-size:12px; line-height:1.7; } .date-line { line-height:1.7; }
</style>
