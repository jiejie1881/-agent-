<script setup lang="ts">
import {computed, ref} from 'vue'
import {comparableProtocol, evaluationEntry, format, metrics, object} from '@/utils/knowledgeEvaluation'
import type {KnowledgeDocument, KnowledgeEvaluation, KnowledgeIndex} from '@/types/knowledge'

const props = defineProps<{indexes: KnowledgeIndex[]; documents: KnowledgeDocument[]; runs: KnowledgeEvaluation[]; activeId?: number | null}>()
const emit = defineEmits<{run: [id: number]}>()
const olderId = ref<number>(), newerId = ref<number>()
const versions = computed(() => [...props.indexes].sort((a, b) => b.id - a.id))
const newer = computed(() => versions.value.find(row => row.id === newerId.value) ?? versions.value[0])
const older = computed(() => versions.value.find(row => row.id === olderId.value && row.id !== newer.value?.id) ??
  versions.value.find(row => row.id === props.activeId && row.id !== newer.value?.id) ??
  versions.value.find(row => row.id !== newer.value?.id))
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]))
}
const display = (value: unknown) => value === undefined || value === null ? '—' :
  typeof value === 'object' ? JSON.stringify(canonical(value)) : String(value)
const configLabels: Record<string, string> = {
  chunk_overlap: 'Chunk 重叠长度', chunk_size: 'Chunk 长度', dictionary: '分词词典',
  embedding_client: 'Embedding 客户端', embedding_endpoint_sha256: '向量端点摘要',
  embedding_model: '向量模型配置', embedding_provider: '向量供应商',
  lexical_policy: '词法策略', tokenizer: '分词器',
}
const configRows = computed(() => {
  if (!older.value || !newer.value) return []
  function fields(index: KnowledgeIndex): Record<string, unknown> {
    return {'Embedding 模型': index.embedding_model, '模型修订': index.model_revision, '向量维度': index.dimension,
      ...Object.fromEntries(Object.entries(index.configuration).map(([key, value]) => ['索引配置 · ' + key, value]))}
  }
  const before = fields(older.value), after = fields(newer.value)
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].map(key => ({
    key, label: configLabels[key.replace('索引配置 · ', '')] ?? key, before: display(before[key]), after: display(after[key]),
    changed: JSON.stringify(canonical(before[key])) !== JSON.stringify(canonical(after[key])),
  }))
})
const documentChanges = computed(() => {
  const before = older.value?.snapshot, after = newer.value?.snapshot
  if (!before || !after) return null
  const names = new Map(props.documents.map(doc => [String(doc.id), doc.title]))
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(id => before[id] !== after[id])
    .map(id => ({id, label: names.get(id) ?? '文档 #' + id, before: before[id], after: after[id],
      kind: before[id] === undefined ? '新增' : after[id] === undefined ? '移除' : '版本更新'}))
})
function missedGold(row: Record<string, unknown>) {
  const gold = Array.isArray(row.expected) ? row.expected : []
  if (!gold.length || !Array.isArray(row.returned)) return false
  return !row.returned.some(hit => gold.includes(typeof hit === 'string' ? hit : object(hit).chunk_id))
}
const pairs = computed(() => {
  const left = new Map<string, ReturnType<typeof evaluationEntry>>()
  const right = new Map<string, ReturnType<typeof evaluationEntry>>()
  for (const run of [...props.runs].sort((a, b) => b.id - a.id)) {
    const side = run.index_id === older.value?.id ? left : run.index_id === newer.value?.id ? right : null
    if (!side) continue
    const entry = evaluationEntry(run), key = comparableProtocol(entry)
    if (key && !side.has(key)) side.set(key, entry)
  }
  return [...right].flatMap(([key, after]) => {
    const before = left.get(key)
    if (!before) return []
    const baselineCases = new Map(before.run.cases.map(row => [row.id, row]))
    const changedCases = after.run.cases.flatMap(row => {
      const previous = baselineCases.get(row.id)
      if (!previous || missedGold(previous) === missedGold(row)) return []
      return [{id: String(row.id), query: typeof row.query === 'string' ? row.query : undefined,
        change: missedGold(row) ? '新增完全漏召回' : '恢复 Gold 命中'}]
    })
    return [{before, after, changedCases, scores: metrics.flatMap((metric, i) => {
      const a = before.values[i], b = after.values[i]
      if (a == null || b == null) return []
      const delta = ((b - a) * 100).toFixed(2)
      return [{key: metric.key, label: metric.name + (metric.cutoff ? '@' + after.k : ''),
        before: format(a), after: format(b), delta: (Number(delta) > 0 ? '+' : '') + (Number(delta) === 0 ? '0.00' : delta)}]
    })}]
  }).filter(pair => pair.scores.length)
})
</script>

<template>
  <section v-if="newer" class="version-workspace" aria-label="历史索引对比">
    <h3>历史索引对比</h3>
    <p>选择同一知识库的两个索引快照。此处的选择用于查看证据，发布操作使用上方所选索引。</p>
    <div class="version-selects">
      <label v-if="older">基准索引
        <select :value="older.id" @change="olderId = Number(($event.target as HTMLSelectElement).value)">
          <option v-for="row in versions" :key="row.id" :value="row.id" :disabled="row.id === newer.id">#{{ row.id }} · {{ row.status }}</option>
        </select>
      </label>
      <label>目标索引
        <select :value="newer.id" @change="newerId = Number(($event.target as HTMLSelectElement).value)">
          <option v-for="row in versions" :key="row.id" :value="row.id">#{{ row.id }} · {{ row.status }}</option>
        </select>
      </label>
    </div>
    <div class="version-meta">
      <div v-for="row in [older, newer].filter(index => index !== undefined)" :key="row.id">
        <strong>索引 #{{ row.id }} · {{ row.status }}</strong>
        <small>{{ row.version }}</small>
        <small v-if="row.created_at">创建 {{ row.created_at.slice(0, 19).replace('T', ' ') + ' UTC' }}</small>
        <small v-if="row.published_at">发布 {{ row.published_at.slice(0, 19).replace('T', ' ') + ' UTC' }}</small>
      </div>
    </div>
    <p v-if="!older">已有 1 个索引版本。创建新索引后可查看双版本差异。</p>
    <template v-else>
      <h4>模型与索引配置</h4>
      <div class="version-scroll">
        <table class="config-table">
          <thead><tr><th scope="col">配置项</th><th scope="col">基准 #{{ older.id }}</th><th scope="col">目标 #{{ newer.id }}</th><th scope="col">差异</th></tr></thead>
          <tbody><tr v-for="row in configRows" :key="row.key"><th scope="row" :title="row.key">{{ row.label }}</th><td :title="row.before">{{ row.before }}</td><td :title="row.after">{{ row.after }}</td><td>{{ row.changed ? '有变更' : '一致' }}</td></tr></tbody>
        </table>
      </div>
      <details>
        <summary>查看完整配置</summary>
        <pre>{{ JSON.stringify({baseline: older.configuration, target: newer.configuration}, null, 2) }}</pre>
      </details>
      <h4>文档版本差异</h4>
      <p v-if="!documentChanges">现有记录缺少文档快照。</p>
      <p v-else-if="!documentChanges.length">两个索引记录的文档版本一致。</p>
      <div v-else class="version-scroll">
        <table>
          <thead><tr><th scope="col">文档</th><th scope="col">变更</th><th scope="col">基准文档版本 ID</th><th scope="col">目标文档版本 ID</th></tr></thead>
          <tbody><tr v-for="row in documentChanges" :key="row.id"><th scope="row">{{ row.label }}</th><td>{{ row.kind }}</td><td>{{ row.before ?? '—' }}</td><td>{{ row.after ?? '—' }}</td></tr></tbody>
        </table>
      </div>
      <h4>同口径检索成绩</h4>
      <p v-if="!pairs.length">这两个索引没有可直接比较的完整评测。成绩对比要求测试集摘要、语料版本、策略、K 值、运行范围和逐题 Gold 一致。</p>
      <article v-for="pair in pairs" :key="pair.after.run.id">
        <div class="version-selects">
          <strong>{{ pair.after.run.dataset }} · {{ pair.after.strategy }} · {{ pair.after.scope }}</strong>
          <button type="button" @click="emit('run', pair.before.run.id)">基准批次 #{{ pair.before.run.id }}</button>
          <button type="button" @click="emit('run', pair.after.run.id)">目标批次 #{{ pair.after.run.id }}</button>
        </div>
        <div class="version-scroll">
          <table>
            <thead><tr><th scope="col">指标</th><th scope="col">基准</th><th scope="col">目标</th><th scope="col">差值（百分点）</th></tr></thead>
            <tbody><tr v-for="row in pair.scores" :key="row.key"><th scope="row">{{ row.label }}</th><td>{{ row.before }}</td><td>{{ row.after }}</td><td>{{ row.delta }}</td></tr></tbody>
          </table>
        </div>
        <details v-if="pair.changedCases.length">
          <summary>Gold 完全漏召回变化 · {{ pair.changedCases.length }} 题</summary>
          <ul><li v-for="row in pair.changedCases" :key="row.id">{{ row.change }} · {{ row.query ?? row.id }}</li></ul>
        </details>
        <p v-else>含 Gold 的题目中，是否完全漏召回的结果一致。</p>
      </article>
    </template>
  </section>
</template>

<style scoped>
.version-workspace { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; margin-top: 20px; padding: 16px; scroll-margin-top: 76px; border: 1px solid var(--rag-border); border-radius: 12px; }
h3, h4, p { margin: 0; }
article { min-width: 0; }
article p, article details { margin-top: 8px; overflow-wrap: anywhere; }
summary { cursor: pointer; }
pre { max-height: 300px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
p, small { color: #56647a; }
.version-selects { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; overflow-wrap: anywhere; }
label { display: grid; gap: 4px; font-size: 13px; font-weight: 600; }
select, button { padding: 6px 10px; border: 1px solid #cdd5e3; border-radius: 8px; background: white; color: #19243b; }
button { cursor: pointer; color: var(--rag-accent); }
.version-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); gap: 12px; }
.version-meta > div { background: #f5f7fc; border-radius: 8px; padding: 10px; overflow-wrap: anywhere; }
small { display: block; }
.version-scroll { overflow-x: auto; max-width: 100%; }
table { border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; }
th, td { text-align: start; padding: 8px; border-bottom: 1px solid #e0e6f0; overflow-wrap: anywhere; }
th:last-child, td:last-child { white-space: nowrap; }
thead { background: #f5f7fc; }
.config-table { min-width: 560px; table-layout: fixed; }
.config-table th:first-child { width: 146px; }
.config-table th:last-child { width: 65px; }
.config-table td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
