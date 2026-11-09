<script setup lang="ts">
import type { DailyExceptionReport } from '@/types/daily-exception'
defineProps<{ report: DailyExceptionReport }>()
</script>
<template>
  <div class="exception-grid"><div><strong>{{ report.plan_unassigned.count }}</strong><span>方案内未分配需求</span></div><div><strong>{{ report.pending_outside_reference_plan.count }}</strong><span>方案外待计划需求</span></div><div><strong>{{ report.plan_vehicle_unavailable.count }}</strong><span>车辆出勤异常任务</span></div><div><strong>{{ report.failed_stops.count }}</strong><span>配送失败停靠点</span></div></div>
  <p>各维度按后端口径独立统计，不相加为总异常数。</p>
  <p v-for="notice in report.notices" :key="notice">{{ notice }}</p>
</template>
<style scoped>
.exception-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; } .exception-grid div { padding:14px; background:#faf8f5; border-radius:10px; } strong { display:block; font-size:24px; color:#c48124; } span { display:block; margin-top:7px; font-size:12px; color:#63738c; } p { margin:14px 0 0; font-size:11px; line-height:1.7; color:#8592a6; }
</style>
