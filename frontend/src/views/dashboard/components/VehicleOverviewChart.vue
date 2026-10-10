<script setup lang="ts">
import type { fleetMetrics } from '../metrics'
defineProps<{ overview: ReturnType<typeof fleetMetrics>; planReady: boolean }>()
</script>
<template>
  <el-empty v-if="!overview.total" description="尚未录入车辆" :image-size="80" />
  <template v-else>
    <div class="fleet-summary"><span>出勤 <b>{{ overview.present }}</b></span><span>不可出勤 <b>{{ overview.absent }}</b></span><span>未登记 <b>{{ overview.missing }}</b></span><span>有效出勤 <b>{{ overview.available }}</b></span></div>
    <div v-for="type in overview.types" :key="type.id" class="type-row"><div><strong>{{ type.name }}</strong><small>{{ type.code }}</small><span>{{ type.present }} / {{ type.total }} 辆</span></div><el-progress :percentage="type.total ? type.present / type.total * 100 : 0" :show-text="false" :stroke-width="8" color="#2f80ed" /><p>当前参考方案：{{ planReady ? `${type.trips} 趟任务` : '暂不可统计' }}</p></div>
    <p class="footnote">有效出勤指登记可出勤且车辆、车型均启用；不代表满足全部线路及货物约束。</p>
  </template>
</template>
<style scoped>
.fleet-summary { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; padding-bottom:16px; border-bottom:1px solid #edf1f7; } .fleet-summary span { color:#7a869a; font-size:11px; } b { display:block; font-size:22px; color:#172b4d; margin-top:5px; } .type-row { margin-top:18px; } .type-row>div { display:flex; align-items:center; gap:8px; margin-bottom:9px; font-size:13px; } strong { color:#172b4d; } small { color:#94a3b8; font-size:10px; } .type-row span { margin-left:auto; color:#63738c; } p { font-size:11px; color:#8592a6; margin:7px 0 0; } .footnote { margin-top:17px; line-height:1.7; }
</style>
