import http from '@/api/http'
import type {KnowledgeAudit, KnowledgeBase, KnowledgeChunkPage, KnowledgeDiff, KnowledgeDocument,
  KnowledgeEvaluation, KnowledgeIndex, KnowledgeJob, KnowledgeLabResult, KnowledgeVersion} from '@/types/knowledge'

export const listBases = () => http.get<KnowledgeBase[]>('/knowledge/bases')
export const createBase = (data: {name: string; business_scope: string; visibility: string; read_roles: string[]}) => http.post<KnowledgeBase>('/knowledge/bases', data)
export const updateBase = (id: number, data: {name: string; business_scope: string; visibility: string; read_roles: string[]; expected_revision: number; status: string}) => http.patch<KnowledgeBase>(`/knowledge/bases/${id}`, data)
export const listDocuments = (id: number) => http.get<KnowledgeDocument[]>(`/knowledge/bases/${id}/documents`)
export const uploadDocument = (id: number, file: File, source: string, document?: KnowledgeDocument) => {
  const form = new FormData(); form.append('file', file); form.append('source_label', source)
  if (document) { form.append('document_id', String(document.id)); form.append('expected_revision', String(document.revision)) }
  return http.post<KnowledgeVersion>(`/knowledge/bases/${id}/documents`, form, {headers: {'Content-Type': 'multipart/form-data'}})
}
export const listVersions = (id: number) => http.get<KnowledgeVersion[]>(`/knowledge/documents/${id}/versions`)
export const versionContent = (id: number, versionId: number) => http.get<string>(`/knowledge/documents/${id}/versions/${versionId}/content`, {responseType: 'text'})
export const updateDocumentPermissions = (doc: KnowledgeDocument, visibility: string, read_roles: string[]) => http.patch<KnowledgeDocument>(`/knowledge/documents/${doc.id}/permissions`, {expected_revision: doc.revision, visibility, read_roles})
export const deleteDocument = (doc: KnowledgeDocument) => http.delete(`/knowledge/documents/${doc.id}`, {data: {expected_revision: doc.revision, confirmed: true}})
export const listJobs = (id: number) => http.get<KnowledgeJob[]>(`/knowledge/bases/${id}/jobs`)
export const createJob = (id: number, key: string) => http.post<KnowledgeJob>(`/knowledge/bases/${id}/jobs`, {idempotency_key: key})
export const runJob = (id: number) => http.post<KnowledgeJob>(`/knowledge/jobs/${id}/run`, {}, {timeout: 60_000})
export const retryJob = (id: number) => http.post<KnowledgeJob>(`/knowledge/jobs/${id}/retry`)
export const recoverJob = (id: number) => http.post<KnowledgeJob>(`/knowledge/jobs/${id}/recover`)
export const listIndexes = (id: number) => http.get<KnowledgeIndex[]>(`/knowledge/bases/${id}/indexes`)
export const getChunks = (id: number, offset = 0) => http.get<KnowledgeChunkPage>(`/knowledge/indexes/${id}/chunks`, {params: {offset, limit: 50}})
export const indexDiff = (id: number) => http.get<KnowledgeDiff>(`/knowledge/indexes/${id}/diff`)
export const validateIndex = (id: number, dataset: string, strategy: string) => http.post<KnowledgeEvaluation>(`/knowledge/indexes/${id}/validate`, {dataset, strategy}, {timeout: 60_000})
export const publishIndex = (id: number, base: KnowledgeBase, rollback = false) => http.post<KnowledgeIndex>(`/knowledge/indexes/${id}/${rollback ? 'rollback' : 'publish'}`, {expected_active_id: base.active_index_id, expected_revision: base.revision, confirmed: true})
export const retireIndex = (id: number, base: KnowledgeBase) => http.delete(`/knowledge/indexes/${id}`, {data: {expected_revision: base.revision, confirmed: true}})
export const laboratory = (data: {base_id: number; query: string; strategy: string; top_k: number; index_id?: number}) => http.post<KnowledgeLabResult>('/knowledge/retrieval/preview', data)
export const listEvaluations = (id: number) => http.get<KnowledgeEvaluation[]>(`/knowledge/bases/${id}/evaluations`)
export const knowledgeMetrics = () => http.get<Record<string, unknown>>('/knowledge/metrics')
export const knowledgeAudits = () => http.get<KnowledgeAudit[]>('/knowledge/audits')
