import type {KnowledgeEvaluation} from '@/types/knowledge'

export const metrics = [
  {key: 'recall_at_k', name: 'Recall', label: '召回率', cutoff: true},
  {key: 'precision_at_k', name: 'Precision', label: '准确率', cutoff: true},
  {key: 'mrr', name: 'MRR', label: '平均倒数排名', cutoff: false},
  {key: 'ndcg', name: 'nDCG', label: '归一化折损累计增益', cutoff: true},
] as const
export const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const positive = (value: unknown) => typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : null
export function score(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null
}
export function format(value: number | null) {
  return value === null ? '—' : (value * 100).toFixed(2) + '%'
}
export function evaluationEntry(run: KnowledgeEvaluation) {
  const pipeline = object(run.metrics.pipeline)
  const provenance = object(pipeline.provenance)
  // Use the original completed aggregate for both current and legacy records.
  // Observation reports for interrupted runs can contain scored empty results.
  const size = positive(run.metrics.queries)
  const k = positive(run.metrics.k)
  const scope = typeof run.metrics.scope === 'string' ? run.metrics.scope : ''
  const mode = provenance.strategy ?? run.metrics.strategy ?? (run.dataset === 'document_smoke' ? 'bm25' : '')
  const strategy = typeof mode === 'string' ? mode : ''
  const values = metrics.map(metric => score(run.metrics[metric.key]))
  const complete = !!size && size === run.cases.length && new Set(run.cases.map(row => row.id)).size === size &&
    run.cases.every(row => Array.isArray(row.returned) && (row.status === 'COMPLETED' ||
      (run.dataset === 'document_smoke' && row.status === undefined)))
  const measured = complete && !!k && values.some(value => value !== null)
  const group = measured && scope && strategy && run.dataset_sha256
    ? JSON.stringify([run.index_id, run.dataset, run.dataset_sha256, scope, k, size]) : ''
  return {run, k, size, scope, strategy, values, measured, group, provenance}
}

export type EvaluationEntry = ReturnType<typeof evaluationEntry>

export function comparableProtocol(entry: EvaluationEntry) {
  const {run, measured, scope, k, size, strategy, provenance} = entry
  const corpus = provenance.corpus_version
  if (!measured || !scope || !strategy || !run.dataset_sha256 || typeof corpus !== 'string' || !corpus ||
      provenance.dataset_sha256 !== run.dataset_sha256 || provenance.k !== k) return null
  const gold = run.cases.map(row => [row.id, row.query ?? null,
    Array.isArray(row.expected) ? [...row.expected].sort() : null])
  if (gold.some(([id, , expected]) => typeof id !== 'string' || expected === null)) return null
  gold.sort(([id], [other]) => String(id).localeCompare(String(other)))
  return JSON.stringify([run.dataset, run.dataset_sha256, scope, k, size, strategy, corpus, gold])
}
