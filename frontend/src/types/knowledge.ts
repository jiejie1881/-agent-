export interface KnowledgeBase {
  id: number; name: string; business_scope: string; status: string; visibility: string
  read_roles: string[]; active_index_id: number | null; revision: number; running_job_id: number | null
}
export interface KnowledgeDocument {
  id: number; base_id: number; title: string; current_version_id: number; revision: number
  deleted: boolean; visibility: string; read_roles: string[]
}
export interface KnowledgeVersion {
  id: number; document_id: number; version: number; sha256: string; original_name: string
  source_label: string; stage: string; error_type: string | null
  created_at?: string
}
export interface KnowledgeJob {
  id: number; base_id: number; status: string; stage: string; attempts: number; max_attempts: number
  retryable: boolean; error_type: string | null; result_index_id: number | null; duration_ms: number | null
  model_calls: number | null; cost: string | null
  started_at?: string | null; finished_at?: string | null; failure_message?: string | null
  progress?: {unit: 'stages'; current_step: number; completed_steps: number; total_steps: number}
  timeline?: {action: string; stage: string | null; attempt: number | null; created_at: string}[]
}
export interface KnowledgeIndex {
  id: number; base_id: number; version: string; status: string; validation_kind: string | null
  embedding_model: string; model_revision: string; dimension: number; configuration: Record<string, unknown>
  published_at: string | null; created_at?: string; snapshot?: Record<string, number>
}
export interface KnowledgeChunk {
  chunk_id: string; document_version_id?: number; content: string; source?: string; section?: string
  document_id?: string; index_version?: string; vector_rank?: number | null; bm25_rank?: number | null
  fusion_rank?: number | null; final_rank?: number | null; score?: number | null; bm25_score?: number | null
  rrf_score?: number | null; reranker_score?: number | null; metadata?: Record<string, unknown>
  char_count?: number
}
export interface KnowledgeChunkPage {
  index_version: string; configuration: Record<string, unknown>; chunks: KnowledgeChunk[]
  total_chunks: number; offset: number; limit: number; page_characters: number
}
export interface KnowledgeEvaluation {
  id: number; index_id: number; dataset: string; dataset_sha256: string; status: string
  metrics: Record<string, unknown>; cases: Record<string, unknown>[]; created_at?: string
}
export interface KnowledgeDiff {
  active_index_id: number | null; candidate_index_id: number; added_documents: string[]
  removed_documents: string[]; updated_documents: string[]; model_changed: boolean; quality_status: string
}
export interface KnowledgeLabResult {
  results: KnowledgeChunk[]; candidates: KnowledgeChunk[]; stats: Record<string, unknown>
  evidence_status: string; answerability: string; refusal_reason: string | null; generation: string; scope: string
}
export interface KnowledgeAudit {
  id: number; username: string; action: string; object_type: string; object_id: number | null
  changes: Record<string, unknown> | null; created_at: string
}
