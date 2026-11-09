<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {evaluationEntry, format, metrics, object, score} from '@/utils/knowledgeEvaluation'
import type {KnowledgeEvaluation, KnowledgeIndex} from '@/types/knowledge'

const props = defineProps<{runs: KnowledgeEvaluation[]; indexes: KnowledgeIndex[]; selected?: number}>()
const emit = defineEmits<{select: [id: number | undefined]}>()
const version = ref(''), strategy = ref(''), protocol = ref('')
const statusLabels: Record<string, string> = {PASS: '通过', FAIL: '失败', ERROR: '执行错误',
  PARTIAL: '部分通过', BLOCKED: '已阻塞', 'NOT RUN': '尚未执行', UNKNOWN: '未知', SKIPPED: '已跳过'}
const strategyLabels: Record<string, string> = {bm25: 'BM25 · 关键词', vector: 'Vector · 向量', hybrid: 'Hybrid · 混合'}
const datasetLabels: Record<string, string> = {document_smoke: '文档自检', development: '开发集', fixed: '固定集'}
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const strategyLabel = (key: string) => strategyLabels[key] ?? (key || '—')
const datasetLabel = (key: string) => datasetLabels[key] ?? key
const indexById = computed(() => new Map(props.indexes.map(index => [index.id, index])))
const entries = computed(() => [...props.runs].sort((a, b) => b.id - a.id).map(evaluationEntry))
const versions = computed(() => [...new Set(entries.value.map(row => row.run.index_id))])
const strategies = computed(() => [...new Set(entries.value.filter(row => row.measured && row.strategy).map(row => row.strategy))])
const visible = computed(() => entries.value.filter(row =>
  (!version.value || String(row.run.index_id) === version.value) && (!strategy.value || row.strategy === strategy.value)))
const protocols = computed(() => {
  const groups = new Map<string, typeof entries.value[number]>()
  for (const row of visible.value) {
    if (row.group && !groups.has(row.group)) groups.set(row.group, row)
  }
  return [...groups.values()]
})
const active = computed(() => protocols.value.find(row => row.group === protocol.value) ?? protocols.value[0])
const cohort = computed(() => active.value ? visible.value.filter(row => row.group === active.value?.group) : [])
const comparison = computed(() => [...new Set(cohort.value.map(row => row.strategy))]
  .map(mode => cohort.value.find(row => row.strategy === mode)!))
const leaders = computed(() => {
  if (comparison.value.length < 2 || comparison.value.some(row => row.values[3] === null)) return []
  const best = Math.max(...comparison.value.map(row => row.values[3]!))
  return comparison.value.filter(row => row.values[3] === best)
})
const charts = computed(() => metrics.map((metric, i) => ({
  ...metric, title: metric.name + (metric.cutoff ? '@' + active.value?.k : ''),
  bars: comparison.value.flatMap(row => row.values[i] === null ? [] : [{row, value: row.values[i]}]),
})).filter(chart => chart.bars.length))
const selectedEntry = computed(() => entries.value.find(row => row.run.id === props.selected))
const tableMetrics = computed(() => metrics.filter((_, i) => visible.value.some(row => row.measured && row.values[i] !== null)))
function valueFor(row: typeof entries.value[number], key: string) {
  return row.measured ? row.values[metrics.findIndex(metric => metric.key === key)] ?? null : null
}
const caseIndex = ref(0)
watch(() => props.selected, () => { caseIndex.value = 0 })
const currentCase = computed(() => selectedEntry.value?.run.cases[caseIndex.value])
const hits = computed(() => list(currentCase.value?.returned).map((hit, i) => {
  const record = object(hit), id = typeof hit === 'string' ? hit : record.chunk_id
  return {id, rank: i + 1, source: record.source, section: record.section, content: record.content,
    relevant: Array.isArray(currentCase.value?.expected) ? currentCase.value.expected.includes(id) : null}
}))
function open(id: number) { emit('select', id) }
function pretty(value: unknown) { return JSON.stringify(value, null, 2) }
</script>

<template>
  <section class="evaluation-workspace" aria-label="RAG 检索质量评测">
    <div class="evaluation-heading">
      <div><p class="eyebrow">RETRIEVAL EVALUATION</p><h2>检索质量工作台</h2></div>
      <span>当前知识库 · 最近 {{ runs.length }} 条记录（最多 100 条）</span>
    </div>
    <div v-if="entries.length" class="evaluation-filters">
      <label>索引版本
        <select v-model="version" @change="protocol = ''"><option value="">全部版本</option>
          <option v-for="id in versions" :key="id" :value="String(id)">#{{ id }} {{ indexById.get(id)?.version }}</option>
        </select>
      </label>
      <label v-if="strategies.length">检索策略
        <select v-model="strategy" @change="protocol = ''"><option value="">全部策略</option>
          <option v-for="mode in strategies" :key="mode" :value="mode">{{ strategyLabel(mode) }}</option>
        </select>
      </label>
      <label v-if="active">对比口径
        <select :value="active.group" @change="protocol = ($event.target as HTMLSelectElement).value">
          <option v-for="row in protocols" :key="row.group" :value="row.group">索引 #{{ row.run.index_id }} · {{ datasetLabel(row.run.dataset) }} · K={{ row.k }} · 批次 #{{ row.run.id }}</option>
        </select>
      </label>
    </div>
    <div v-if="active" class="overview">
      <div><span>同口径实验</span><strong>{{ cohort.length }}</strong></div>
      <div><span>已测策略</span><strong>{{ comparison.length }}</strong></div>
      <div><span>测试集规模</span><strong>{{ active.size }} 题</strong></div>
      <div v-if="leaders.length"><span>最高 nDCG@{{ active.k }}</span><strong>{{ leaders.map(row => strategyLabel(row.strategy)).join(" / ") }}</strong></div>
      <div v-if="active.run.created_at"><span>最近评测时间</span><strong>{{ active.run.created_at.slice(0, 19).replace('T', ' ') }} UTC</strong></div>
    </div>
    <section v-if="active" class="chart-section">
      <h3>策略效果</h3>
      <p>索引 #{{ active.run.index_id }} · {{ datasetLabel(active.run.dataset) }} · K={{ active.k }} · {{ active.scope }}</p>
      <p>每种策略显示此口径下最新一条完整实验。文档自检及已公开评测集均用于复测。历史记录可能缺少精排等运行配置，分数仅描述各次实验。</p>
      <div class="charts">
        <article v-for="chart in charts" :key="chart.key" class="chart">
          <h4>{{ chart.title }} <small>{{ chart.label }}</small></h4>
          <div v-for="{row, value} in chart.bars" :key="row.run.id" class="bar-row">
            <button type="button" @click="open(row.run.id)">{{ strategyLabel(row.strategy) }} <small>#{{ row.run.id }}</small></button>
            <strong>{{ format(value) }}</strong>
            <progress :value="value" max="1" :aria-label="chart.title + ' ' + strategyLabel(row.strategy)">{{ format(value) }}</progress>
          </div>
        </article>
      </div>
    </section>
    <p v-else class="empty-note">{{ runs.length ? '当前筛选范围没有可用于对比的完整检索成绩。' : '当前知识库还没有评测记录。' }}</p>
    <section v-if="visible.length">
      <h3>策略实验记录</h3>
      <div class="table-scroll">
        <table>
          <thead><tr><th scope="col">评测批次</th><th scope="col">索引</th><th scope="col">评测集</th><th scope="col">策略</th><th scope="col">K</th>
            <th v-for="metric in tableMetrics" :key="metric.key" scope="col">{{ metric.name }}{{ metric.cutoff ? '@K' : '' }}</th><th scope="col">状态</th></tr></thead>
          <tbody><tr v-for="row in visible" :key="row.run.id">
            <th scope="row"><button type="button" @click="open(row.run.id)">#{{ row.run.id }} 查看</button></th><td>#{{ row.run.index_id }}</td>
            <td>{{ datasetLabel(row.run.dataset) }}</td><td>{{ strategyLabel(row.strategy) }}</td><td>{{ row.k ?? '—' }}</td>
            <td v-for="metric in tableMetrics" :key="metric.key">{{ format(valueFor(row, metric.key)) }}</td>
            <td><span class="run-status" :data-status="row.run.status" :title="row.run.status">{{ statusLabels[row.run.status] ?? row.run.status }}</span></td>
          </tr></tbody>
        </table>
      </div>
    </section>
    <el-drawer :model-value="!!selectedEntry" :title="'评测批次 #' + selectedEntry?.run.id"
      size="min(760px, 100vw)" destroy-on-close @close="emit('select', undefined)">
      <div v-if="selectedEntry" class="evidence">
        <p>{{ datasetLabel(selectedEntry.run.dataset) }} · {{ strategyLabel(selectedEntry.strategy) }} · 索引 #{{ selectedEntry.run.index_id }} · {{ selectedEntry.run.created_at }}</p>
        <p v-if="selectedEntry.run.metrics.reason">运行原因：{{ selectedEntry.run.metrics.reason }}</p>
        <pre v-if="selectedEntry.run.metrics.missing">{{ pretty(selectedEntry.run.metrics.missing) }}</pre>
        <details><summary>数据来源与实验配置</summary>
          <p>评测集 SHA-256：{{ selectedEntry.run.dataset_sha256 }}</p><p>{{ selectedEntry.scope }}</p>
          <pre v-if="Object.keys(selectedEntry.provenance).length">{{ pretty(selectedEntry.provenance) }}</pre>
          <pre v-if="indexById.has(selectedEntry.run.index_id)">{{ pretty(indexById.get(selectedEntry.run.index_id)) }}</pre>
        </details>
        <template v-if="currentCase">
          <label>逐题结果
            <select v-model.number="caseIndex"><option v-for="(row, i) in selectedEntry.run.cases" :key="i" :value="i">{{ i + 1 }} · {{ row.id }}</option></select>
          </label>
          <h3>{{ currentCase.query || '检索样本 ' + (caseIndex + 1) }}</h3>
          <p v-if="currentCase.error_type">执行错误：{{ currentCase.error_type }}</p>
          <p v-if="Array.isArray(currentCase.expected)">Gold Chunk：{{ currentCase.expected.join('、') || '空标注（无答案样本）' }}</p>
          <p v-for="metric in metrics.filter(metric => score(object(currentCase?.metrics)[metric.key]) !== null)" :key="metric.key">{{ metric.name }}{{ metric.cutoff ? '@' + selectedEntry.k : '' }} · {{ format(score(object(currentCase.metrics)[metric.key])) }}</p>
          <ol v-if="hits.length">
            <li v-for="hit in hits" :key="hit.rank"><strong>{{ hit.source || hit.id }}</strong>
              <span v-if="hit.section"> · {{ hit.section }}</span>
              <span v-if="hit.relevant !== null"> · {{ hit.relevant ? '命中 Gold' : '未命中 Gold' }}</span>
              <p v-if="hit.content">{{ hit.content }}</p>
            </li>
          </ol>
          <p v-else>此样本无召回记录。</p>
          <details><summary>单题原始执行证据</summary><pre>{{ pretty(currentCase) }}</pre></details>
        </template>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.evaluation-workspace { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; min-width: 0; }
.evaluation-heading { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: end; gap: 8px; }
.evaluation-heading h2, h3, h4, p { margin: 0; }
.eyebrow { color: var(--rag-accent, #4948bc); font-size: 11px; font-weight: 750; letter-spacing: .12em; }
.evaluation-heading span, .chart-section p, small, .overview span { color: #56647a; }
.evaluation-filters { display: flex; flex-wrap: wrap; gap: 12px; }
label { display: grid; gap: 5px; min-width: 0; font-size: 13px; font-weight: 600; }
select { max-width: min(100%, 320px); padding: 8px; background: white; color: #17243b; border: 1px solid #cdd5e3; border-radius: 8px; }
.overview, .charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); gap: 12px; }
.overview { grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr)); }
.overview > div, .chart, .empty-note { padding: 14px; border: 1px solid #e0e6f0; border-radius: 12px; background: #fafbff; min-width: 0; }
.overview strong { display: block; margin-top: 5px; overflow-wrap: anywhere; }
.chart-section { display: grid; gap: 8px; overflow-wrap: anywhere; }
.bar-row { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 4px; margin-top: 12px; font-size: 13px; }
progress { grid-column: 1 / -1; appearance: none; border: 0; height: 8px; width: 100%; border-radius: 9px; overflow: hidden; color: var(--rag-accent, #4948bc); background: #e9ebfa; }
progress::-webkit-progress-bar { background: #e9ebfa; }
progress::-webkit-progress-value { background: #5754cf; border-radius: 9px; }
progress::-moz-progress-bar { background: #5754cf; }
button { text-align: start; border: 0; background: transparent; color: #4948bc; cursor: pointer; font: inherit; padding: 4px 0; }
button:hover { text-decoration: underline; }
.table-scroll { max-width: 100%; overflow-x: auto; margin-top: 10px; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; white-space: nowrap; }
th, td { text-align: start; padding: 10px; border-bottom: 1px solid #e0e6f0; }
thead { background: #f5f7fc; }
.run-status { padding: 4px 8px; border-radius: 16px; background: #edf0f7; font-size: 12px; }
.run-status[data-status="PASS"] { background: #e6f6ee; color: #126341; }
.run-status[data-status="FAIL"], .run-status[data-status="ERROR"] { background: #fce9eb; color: #9b2636; }
.run-status[data-status="BLOCKED"] { background: #fff1d8; color: #784b08; }
.evidence { display: grid; gap: 12px; overflow-wrap: anywhere; }
.evidence select { width: 100%; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 360px; overflow: auto; }
</style>
