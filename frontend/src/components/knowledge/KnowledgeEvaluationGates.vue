<script setup lang="ts">
import {computed} from 'vue'

const props = defineProps<{evaluation: {status: string; metrics: Record<string, unknown>}}>()
const labels = [
  ['retrieval', '检索排序'], ['retrieval_abstention', '无答案拒答'],
  ['semantic_answerability', '证据充分性'], ['final_generation', '最终回答'],
  ['real_reranker', '真实精排'], ['overall', '整体准入'],
] as const
const known = new Set(['PASS', 'FAIL', 'PARTIAL', 'BLOCKED', 'NOT RUN', 'NOT VERIFIED'])
const gates = computed(() => {
  const value = props.evaluation.metrics.acceptance_gates
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
})
function status(key: string) {
  const value = gates.value[key]
  return typeof value === 'string' && known.has(value) ? value : 'NOT VERIFIED'
}
</script>

<template>
  <section aria-label="评测分层验收状态">
    <p>历史指标状态：{{ evaluation.status }}（仅原评测口径，不代表整体准入）</p>
    <p>以下门禁来自后端评测记录；缺少记录保持 NOT VERIFIED。离线或合成数据成绩不能证明真实模型效果。</p>
    <table>
      <caption>独立验收门禁</caption>
      <thead><tr><th scope="col">验收层</th><th scope="col">记录状态</th></tr></thead>
      <tbody><tr v-for="[key, label] in labels" :key="key"><th scope="row">{{ label }}</th><td>{{ status(key) }}</td></tr></tbody>
    </table>
  </section>
</template>

<style scoped>
table {border-collapse: collapse; width: 100%; margin-block: 12px}
th, td {border: 1px solid var(--el-border-color); padding: 8px; text-align: left}
</style>
