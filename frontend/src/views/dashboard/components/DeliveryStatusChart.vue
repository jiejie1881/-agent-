<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ items: { code: string; label: string; color: string; count: number }[] }>()
const total = computed(() => props.items.reduce((sum, i) => sum + i.count, 0))
const slices = computed(() => {
  let offset = 0
  return props.items.map(i => { const length = total.value ? i.count / total.value * 100 : 0; const slice = { ...i, length, offset }; offset += length; return slice })
})
</script>
<template>
  <el-empty v-if="!total" description="该日期暂无有效配送需求" :image-size="80" />
  <div v-else class="status-chart">
    <div class="ring"><svg viewBox="0 0 120 120" role="img" :aria-label="items.map(i => `${i.label} ${i.count}`).join('，')"><circle cx="60" cy="60" r="48" fill="none" stroke="#eef2f7" stroke-width="13" /><circle v-for="slice in slices" :key="slice.code" cx="60" cy="60" r="48" fill="none" :stroke="slice.color" stroke-width="13" pathLength="100" :stroke-dasharray="`${slice.length} ${100 - slice.length}`" :stroke-dashoffset="-slice.offset" transform="rotate(-90 60 60)" /></svg><div class="center"><strong>{{ total }}</strong><span>有效需求</span></div></div>
    <ul><li v-for="item in items" :key="item.code"><span><i :style="{ background: item.color }" />{{ item.label }}</span><b>{{ item.count }}</b><small>{{ (item.count / total * 100).toFixed(1) }}%</small></li></ul>
  </div>
</template>
<style scoped>
.status-chart { display:flex; align-items:center; gap:30px; min-height:205px; } .ring { position:relative; width:190px; flex-shrink:0; } svg { width:100%; display:block; } .center { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; flex-direction:column; } strong { color:#172b4d; font-size:32px; } .center span { font-size:12px; color:#8592a6; margin-top:5px; } ul { padding:0; margin:0; flex:1; list-style:none; } li { display:flex; align-items:center; gap:12px; padding:10px 0; font-size:13px; color:#63738c; } li span { flex:1; display:flex; align-items:center; gap:8px; } i { width:8px; height:8px; border-radius:50%; } b { color:#172b4d; } small { width:46px; text-align:right; color:#8592a6; }
@media(max-width:600px) { .status-chart { flex-direction:column; gap:12px; } ul { width:100%; } }
</style>
