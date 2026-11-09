import http from '@/api/http'
export type ImportKind = 'stores' | 'routes' | 'vehicles' | 'demands'
export interface ImportBatch {
  id: number; kind: ImportKind; status: 'PREVIEW' | 'INVALID' | 'IMPORTED'
  rows: Record<string, string>[]; errors: {row: number; message: string}[]
  result_ids: number[]; expires_at: string; created_at: string
}
export const getImportBatch = (id: number) => http.get<ImportBatch>(`/business-imports/${id}`)
export const listImportBatches = (offset = 0) => http.get<ImportBatch[]>('/business-imports', {params: {offset, limit: 20}})
export const confirmImport = (id: number) => http.post<ImportBatch>(`/business-imports/${id}/confirm`, {confirmed: true})
export const previewImport = (kind: ImportKind, file: File) => {
  const form = new FormData(); form.append('file', file)
  return http.post<ImportBatch>(`/business-imports/${kind}/preview`, form, {headers: {'Content-Type': 'multipart/form-data'}})
}
export async function downloadImportTemplate(kind: ImportKind, format: 'csv' | 'xlsx') {
  const {data} = await http.get<Blob>(`/business-imports/templates/${kind}`, {params: {format, language: 'zh'}, responseType: 'blob'})
  const url = URL.createObjectURL(data), link = document.createElement('a')
  link.href = url; link.download = `${({stores:'门店', routes:'线路', vehicles:'车辆', demands:'配送需求'})[kind]}-中文模板.${format}`; link.click(); URL.revokeObjectURL(url)
}
