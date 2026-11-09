<script setup lang="ts">
import {computed, onMounted, ref} from 'vue'
import {ElMessageBox} from 'element-plus'
import {useAuthStore} from '@/stores/auth'
import * as api from '@/api/knowledge'
import KnowledgeVersionCompare from '@/components/knowledge/KnowledgeVersionCompare.vue'
import {evaluationEntry, format} from '@/utils/knowledgeEvaluation'
import KnowledgeEvaluationAnalysis from '@/components/knowledge/KnowledgeEvaluationAnalysis.vue'
import type {KnowledgeAudit, KnowledgeBase, KnowledgeChunk, KnowledgeDiff, KnowledgeDocument,
  KnowledgeEvaluation, KnowledgeIndex, KnowledgeJob, KnowledgeLabResult, KnowledgeVersion} from '@/types/knowledge'

const auth = useAuthStore(), canManage = computed(() => auth.user?.role === 'ADMIN')
const busy = ref(false), error = ref(''), tab = ref('overview'), baseId = ref<number>(), indexId = ref<number>()
const success = ref(''), creatingBase = ref(false), fileInput = ref<HTMLInputElement | null>(null), jobId = ref<number>()
const chunkTotal = ref<number | null>(null), chunkCharacters = ref(0)
const bases = ref<KnowledgeBase[]>([]), documents = ref<KnowledgeDocument[]>([]), jobs = ref<KnowledgeJob[]>([])
const indexes = ref<KnowledgeIndex[]>([]), evaluations = ref<KnowledgeEvaluation[]>([]), audits = ref<KnowledgeAudit[]>([])
const metrics = ref<Record<string, unknown>>({}), chunks = ref<KnowledgeChunk[]>([]), chunkOffset = ref(0)
const base = computed(() => bases.value.find(x => x.id === baseId.value)), index = computed(() => indexes.value.find(x => x.id === indexId.value))
const name = ref(''), businessScope = ref(''), visibility = ref('ADMIN'), roles = ref<string[]>([]), baseStatus = ref('ACTIVE')
const documentId = ref<number>(), sourceLabel = ref('upload'), file = ref<File | null>(null)
const versions = ref<KnowledgeVersion[]>([]), versionText = ref(''), documentVisibility = ref('INHERIT'), documentRoles = ref<string[]>([])
const document = computed(() => documents.value.find(x => x.id === documentId.value))
const query = ref(''), strategy = ref('vector'), topK = ref(4), candidatePreview = ref(false), result = ref<KnowledgeLabResult | null>(null)
const lastStrategy = ref('')
const retrievalStages = computed(() => {
  if (!result.value) return []
  const stats = result.value.stats
  return [
    {label: 'BM25 候选', value: stats.bm25_candidates, show: lastStrategy.value !== 'vector'},
    {label: '向量候选', value: stats.vector_candidates, show: lastStrategy.value !== 'bm25'},
    {label: '合并去重后', value: stats.unique_candidates, show: lastStrategy.value === 'hybrid'},
    {label: '最终召回', value: result.value.results.length, show: true},
  ].filter(stage => stage.show && typeof stage.value === 'number')
})
const dataset = ref('document_smoke'), evaluationStrategy = ref('bm25'), evaluationId = ref<number>()
const documentDrawer = ref(false), chunkDetail = ref<KnowledgeChunk>()
const navigation = [
  {label: '工作台', items: [{key: 'overview', label: 'RAG 总览'}]},
  {label: '知识资产', items: [{key: 'bases', label: '知识库管理'}, {key: 'documents', label: '文档管理'}, {key: 'chunks', label: 'Chunk预览'}]},
  {label: '检索与评测', items: [{key: 'lab', label: '检索实验室'}, {key: 'evaluations', label: '评测中心'}]},
  {label: '运维治理', items: [{key: 'indexes', label: '索引管理'}, {key: 'monitor', label: '运行监控'}, {key: 'audits', label: '审计管理'}]},
]
const sections = navigation.flatMap(group => group.items)
const currentSection = computed(() => sections.find(item => item.key === tab.value))
const activeIndex = computed(() => indexes.value.find(row => row.id === base.value?.active_index_id))
const activeQuality = computed(() => activeIndex.value ? evaluations.value
  .filter(row => row.index_id === activeIndex.value?.id)
  .map(evaluationEntry).find(row => row.measured) : undefined)
const recentActivity = computed(() => audits.value.filter(row => row.action !== 'RAG_JOB_STAGE').slice(0, 5))
const activityLabels: Record<string, string> = {
  RAG_BASE_CREATED: '新建知识库', RAG_DOCUMENT_UPLOADED: '上传文档', RAG_JOB_COMPLETED: '完成索引构建',
  RAG_JOB_FAILED: '索引构建失败', RAG_INDEX_VALIDATED: '索引自检', RAG_EVALUATION_COMPLETED: '完成检索评测',
  RAG_INDEX_PUBLISHED: '发布索引', RAG_INDEX_ROLLED_BACK: '回退索引', RAG_SEARCHED: '执行检索',
}
const retrievalCount = computed(() => typeof metrics.value.retrieval_count === 'number' ? metrics.value.retrieval_count : null)
const retrievalP50 = computed(() => typeof metrics.value.retrieval_p50_ms === 'number' ? metrics.value.retrieval_p50_ms : null)
function inspectEvaluation(id: number) {
  evaluationId.value = id
  tab.value = 'evaluations'
}
const diff = ref<KnowledgeDiff | null>(null), pendingBuildKey = ref('')
const documentSearch = ref(''), documentState = ref('all'), chunkSearch = ref('')
const filteredDocuments = computed(() => documents.value.filter(row =>
  row.title.toLocaleLowerCase().includes(documentSearch.value.trim().toLocaleLowerCase()) &&
  (documentState.value === 'all' || row.deleted === (documentState.value === 'deleted'))))
const filteredChunks = computed(() => chunks.value.filter(row =>
  row.content.toLocaleLowerCase().includes(chunkSearch.value.trim().toLocaleLowerCase())))
const selectedJob = computed(() => jobs.value.find(row => row.id === jobId.value))
function message(e: unknown) { return e && typeof e === 'object' && 'message' in e ? String(e.message) : String(e) }
function pretty(value: unknown) { return JSON.stringify(value, null, 2) }
function chooseBase(resetSelection = true) {
  const b = base.value; name.value = b?.name ?? ''; businessScope.value = b?.business_scope ?? ''
  visibility.value = b?.visibility ?? 'ADMIN'; roles.value = [...(b?.read_roles ?? [])]; baseStatus.value = b?.status ?? 'ACTIVE'
  if (resetSelection) {
    documentId.value = undefined; versions.value = []; versionText.value = ''; diff.value = null; result.value = null
    indexId.value = undefined; file.value = null; pendingBuildKey.value = ''
    chunks.value = []; chunkOffset.value = 0; chunkTotal.value = null; chunkCharacters.value = 0
    documents.value = []; jobs.value = []; indexes.value = []; evaluations.value = []
    documentDrawer.value = false; chunkDetail.value = undefined
    evaluationId.value = undefined; jobId.value = undefined; success.value = ''; error.value = ''
    documentSearch.value = ''; documentState.value = 'all'; chunkSearch.value = ''
    if (fileInput.value) fileInput.value.value = ''
  }
}
function chooseIndex() { chunks.value = []; chunkOffset.value = 0; chunkTotal.value = null; chunkCharacters.value = 0; diff.value = null }
async function load() {
  bases.value = (await api.listBases()).data
  if (!creatingBase.value && !bases.value.some(b => b.id === baseId.value)) baseId.value = bases.value[0]?.id
  if (baseId.value) {
    const responses = await Promise.all([api.listDocuments(baseId.value), api.listJobs(baseId.value), api.listIndexes(baseId.value), api.listEvaluations(baseId.value)])
    documents.value = responses[0].data; jobs.value = responses[1].data; indexes.value = responses[2].data; evaluations.value = responses[3].data
    if (!indexes.value.some(i => i.id === indexId.value)) indexId.value = base.value?.active_index_id ?? indexes.value[0]?.id
    if (!documents.value.some(d => d.id === documentId.value)) { documentId.value = undefined; versions.value = []; versionText.value = '' }
  } else { documents.value = []; jobs.value = []; indexes.value = []; evaluations.value = [] }
  metrics.value = (await api.knowledgeMetrics()).data; audits.value = (await api.knowledgeAudits()).data
  if (!creatingBase.value) chooseBase(false)
}
async function act(action: () => Promise<unknown>) {
  if (busy.value || !canManage.value) return
  busy.value = true; error.value = ''; success.value = ''
  try { await action(); await load(); if (!error.value) success.value = '操作已完成' }
  catch(e) { if (e !== 'cancel' && e !== 'close') error.value = message(e); try { await load() } catch {} }
  finally { busy.value = false }
}
async function refresh() { await act(async () => {}) }
async function selectBase() { if (busy.value) return; creatingBase.value = false; chooseBase(); await refresh() }
function newBase() { if (busy.value || !canManage.value) return; creatingBase.value = true; tab.value = 'bases'; baseId.value = undefined; chooseBase() }
async function saveBase() {
  if (!name.value.trim()) return
  await act(async () => {
    const data = {name: name.value, business_scope: businessScope.value, visibility: visibility.value, read_roles: roles.value}
    const response = base.value ? await api.updateBase(base.value.id, {...data, status: baseStatus.value, expected_revision: base.value.revision}) : await api.createBase(data)
    baseId.value = response.data.id
    creatingBase.value = false
  })
}
function selected(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] ?? null }
async function upload() {
  if (!base.value || !file.value || !canManage.value || busy.value) return
  if (file.value.size > 5 * 1024 * 1024 || !/\.(md|txt)$/i.test(file.value.name)) { error.value = '仅支持不超过5MB的Markdown/TXT文档'; return }
  await act(async () => { await api.uploadDocument(base.value!.id, file.value!, sourceLabel.value, document.value); file.value = null; if (fileInput.value) fileInput.value.value = '' })
}
async function openDocument(row: KnowledgeDocument) {
  documentDrawer.value = true; versions.value = []; versionText.value = ''
  documentId.value = row.id; documentVisibility.value = row.visibility; documentRoles.value = [...row.read_roles]
  await act(async () => { versions.value = (await api.listVersions(row.id)).data; versionText.value = '' })
}
async function readVersion(row: KnowledgeVersion) { await act(async () => { versionText.value = (await api.versionContent(row.document_id, row.id)).data }) }
async function savePermissions() { if (document.value) await act(() => api.updateDocumentPermissions(document.value!, documentVisibility.value, documentRoles.value)) }
async function removeDocument(row: KnowledgeDocument) {
  await act(async () => { await ElMessageBox.confirm('确认逻辑删除？检索将立即隐藏，历史文件与审计保留。', '删除知识文档', {type: 'warning'}); await api.deleteDocument(row) })
}
async function createBuild() {
  if (!base.value) return
  await act(async () => {
    pendingBuildKey.value ||= crypto.randomUUID()
    await api.createJob(base.value!.id, pendingBuildKey.value)
    pendingBuildKey.value = ''
  })
}
async function runBuild(row: KnowledgeJob) { await act(async () => { const response = await api.runJob(row.id); jobId.value = row.id; if (response.data.status === 'FAILED') error.value = response.data.failure_message || '构建失败，请查看任务详情。' }) }
async function retryBuild(row: KnowledgeJob) { await act(() => api.retryJob(row.id)) }
async function recoverBuild(row: KnowledgeJob) { await act(() => api.recoverJob(row.id)) }
async function previewChunks() { if (indexId.value) await act(async () => { const page = (await api.getChunks(indexId.value!, chunkOffset.value)).data; chunks.value = page.chunks; chunkTotal.value = page.total_chunks; chunkCharacters.value = page.page_characters }) }
async function pageChunks(delta: number) { chunkOffset.value = Math.max(0, chunkOffset.value + delta); await previewChunks() }
async function compareIndex() { if (indexId.value) await act(async () => { diff.value = (await api.indexDiff(indexId.value!)).data }) }
async function validate() {
  if (!indexId.value) return
  await act(async () => { const value = (await api.validateIndex(indexId.value!, dataset.value, evaluationStrategy.value)).data; evaluationId.value = value.id })
}
async function publish(rollback = false) {
  if (!base.value || !index.value) return
  const target = index.value.id, expectedBase = {...base.value}
  await act(async () => {
    diff.value = (await api.indexDiff(target)).data
    await ElMessageBox.confirm(`${rollback ? '回退' : '发布'}已验证版本？新增${diff.value.added_documents.length}份、更新${diff.value.updated_documents.length}份、移除${diff.value.removed_documents.length}份。只切换活动引用，不覆盖上传历史。文档自检不代表回答质量或独立盲测通过，请核对验证范围。`, '人工确认索引切换', {type: 'warning'})
    await api.publishIndex(target, expectedBase, rollback)
  })
}
async function retire() {
  if (!base.value || !index.value) return
  await act(async () => { await ElMessageBox.confirm('确认退役此非活动索引？历史文件与审计继续保留。', '退役索引', {type: 'warning'}); await api.retireIndex(index.value!.id, base.value!) })
}
async function search() {
  if (!base.value || !query.value.trim()) return
  if (candidatePreview.value && !indexId.value) { error.value = '请先选择候选索引'; return }
  await act(async () => {
    const request = {base_id: base.value!.id, query: query.value, strategy: strategy.value,
      top_k: topK.value, ...(candidatePreview.value && indexId.value ? {index_id: indexId.value} : {})}
    result.value = null
    result.value = (await api.laboratory(request)).data
    lastStrategy.value = request.strategy
  })
}
onMounted(async () => { await refresh(); success.value = ''; chooseBase(false) })
</script>

<template>
  <section class="knowledge-page">
    <header class="rag-heading">
      <div><p>知识治理 / {{ currentSection?.label }}</p><h1>RAG 管理平台</h1></div>
      <div class="header-actions">
        <el-select :model-value="tab" filterable aria-label="搜索 RAG 页面" placeholder="搜索 RAG 页面" @change="tab = $event">
          <el-option v-for="item in sections" :key="item.key" :label="item.label" :value="item.key" />
        </el-select>
        <RouterLink :to="{ name: 'agent-chat' }">返回 Agent 聊天</RouterLink>
      </div>
    </header>
    <el-alert title="请以索引模型及结果scope核对运行范围；合成结果不代表真实模型效果。构建、验证、发布是三个独立操作。" type="warning" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="success && !error" :title="success" type="success" :closable="false" />
    <el-alert v-if="!canManage" title="知识治理管理需要管理员权限。" type="error" :closable="false" />
    <p v-if="busy" role="status">正在处理，请稍候…</p>
    <div class="toolbar">
      <el-select v-model="baseId" :disabled="busy" placeholder="选择知识库" @change="selectBase"><el-option v-for="b in bases" :key="b.id" :label="b.name" :value="b.id" /></el-select>
      <el-button :loading="busy" @click="refresh">刷新</el-button><el-button :disabled="busy || !canManage" @click="newBase">新建知识库</el-button>
      <span v-if="base">状态 {{ base.status }} · 活动索引 {{ base.active_index_id ?? '未发布' }} · 版本 {{ base.revision }}</span>
    </div>
    <el-empty v-if="!busy && !bases.length && !creatingBase" description="尚无知识库，请先新建知识库。" />
    <div class="rag-layout">
      <nav class="rag-nav" aria-label="RAG 功能导航">
        <div v-for="group in navigation" :key="group.label">
          <p>{{ group.label }}</p>
          <button v-for="item in group.items" :key="item.key" type="button"
            :aria-current="tab === item.key ? 'page' : undefined" @click="tab = item.key">{{ item.label }}</button>
        </div>
      </nav>
      <div class="rag-content" v-loading="busy">
    <el-tabs v-model="tab" class="rag-tabs">
      <el-tab-pane label="RAG 总览" name="overview" lazy>
        <div class="section-title"><h2>RAG 总览</h2><p>当前知识库的资料、活动索引与验证记录。</p></div>
        <div class="overview-grid">
          <article><small>可管理知识库</small><strong>{{ bases.length }}</strong></article>
          <article><small>当前库保留文档</small><strong>{{ documents.filter(row => !row.deleted).length }}</strong></article>
          <article><small>活动索引</small><strong>{{ base?.active_index_id ? '#' + base.active_index_id : '未发布' }}</strong></article>
          <article><small>当前库最近评测</small><strong>{{ evaluations[0] ? '#' + evaluations[0].id + ' · ' + evaluations[0].status : '暂无记录' }}</strong></article>
        </div>
        <div class="overview-grid overview-panels">
          <article v-if="activeIndex">
            <h3>活动索引配置</h3>
            <dl class="summary-fields">
              <dt>Embedding 模型</dt><dd>{{ activeIndex.embedding_model }}</dd>
              <dt>向量维度</dt><dd>{{ activeIndex.dimension }}</dd>
              <dt>索引状态</dt><dd>{{ activeIndex.status }}</dd>
              <template v-if="activeIndex.snapshot"><dt>快照文档数</dt><dd>{{ Object.keys(activeIndex.snapshot).length }}</dd></template>
            </dl>
          </article>
          <article v-if="activeQuality">
            <h3>活动索引最近完整评测</h3>
            <p>{{ activeQuality.run.dataset }} · {{ activeQuality.strategy }} · K={{ activeQuality.k }}</p>
            <p v-if="activeQuality.values[0] !== null">Recall@{{ activeQuality.k }} · {{ format(activeQuality.values[0] ?? null) }}</p>
            <p v-if="activeQuality.values[3] !== null">nDCG@{{ activeQuality.k }} · {{ format(activeQuality.values[3] ?? null) }}</p>
            <el-button text type="primary" @click="inspectEvaluation(activeQuality.run.id)">查看批次 #{{ activeQuality.run.id }}</el-button>
          </article>
          <article v-if="retrievalCount !== null">
            <h3>系统检索活动</h3>
            <p>全局最近最多 1000 条检索审计</p>
            <dl class="summary-fields">
              <dt>记录数</dt><dd>{{ retrievalCount }}</dd>
              <template v-if="retrievalP50 !== null"><dt>P50 延迟</dt><dd>{{ retrievalP50.toFixed(1) }} ms</dd></template>
            </dl>
            <el-button text type="primary" @click="tab = 'monitor'">查看运行监控</el-button>
          </article>
        </div>
        <h3>知识库目录</h3>
        <el-table :data="bases">
          <el-table-column prop="name" label="知识库" min-width="140" show-overflow-tooltip />
          <el-table-column prop="business_scope" label="业务范围" min-width="180" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" />
          <el-table-column prop="active_index_id" label="活动索引" />
          <el-table-column prop="revision" label="修订号" />
        </el-table>
        <div class="toolbar"><el-button @click="tab = 'evaluations'">查看检索质量</el-button><el-button @click="tab = 'indexes'">查看构建和版本</el-button></div>
        <template v-if="recentActivity.length">
          <h3>最近治理活动 <small>全局审计</small></h3>
          <ul class="activity-list">
            <li v-for="row in recentActivity" :key="row.id">
              <span :title="row.action">{{ activityLabels[row.action] ?? row.action }}</span>
              <span>{{ row.username }} · {{ row.created_at.slice(0, 19).replace('T', ' ') }} UTC</span>
            </li>
          </ul>
          <el-button text type="primary" @click="tab = 'audits'">查看审计记录</el-button>
        </template>
      </el-tab-pane>
      <el-tab-pane label="知识库管理" name="bases" lazy>
        <div class="section-title"><h2>知识库管理</h2><p>管理业务范围、可见角色与归档状态。</p></div>
        <el-form label-width="100px"><el-form-item label="名称"><el-input v-model="name" maxlength="120" /></el-form-item>
          <el-form-item label="业务范围"><el-input v-model="businessScope" maxlength="300" /></el-form-item>
          <el-form-item label="状态"><el-select v-model="baseStatus"><el-option label="有效" value="ACTIVE" /><el-option label="归档" value="ARCHIVED" /></el-select></el-form-item>
          <el-form-item label="访问范围"><el-select v-model="visibility"><el-option label="仅管理员" value="ADMIN" /><el-option label="管理端用户" value="PUBLIC" /><el-option label="指定角色" value="ROLES" /></el-select></el-form-item>
          <el-form-item v-if="visibility === 'ROLES'" label="允许角色"><el-select v-model="roles" multiple><el-option v-for="r in ['DISPATCHER','VIEWER']" :key="r" :value="r" /></el-select></el-form-item>
          <el-button :disabled="busy || !canManage" @click="saveBase">保存知识库</el-button>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="文档管理" name="documents" lazy>
        <div class="section-title"><h2>文档管理</h2><p>查看文档版本、处理状态及访问权限。</p></div>
        <p>上传生成新版本，旧版本保留。当前已发布内容可能早于最新上传版本。仅支持UTF-8 Markdown/TXT，单文件不超过5MB。</p>
        <div class="toolbar"><input ref="fileInput" type="file" accept=".md,.txt" :disabled="busy" @change="selected" /><el-input v-model="sourceLabel" maxlength="300" placeholder="来源说明（不自动抓取网址）" />
          <el-button :disabled="busy || !base || document?.deleted" @click="upload">{{ document ? '上传此文档新版本' : '上传新文档' }}</el-button>
          <el-button @click="documentId = undefined; versions = []; versionText = ''">清除文档选择</el-button></div>
        <div class="toolbar"><el-input v-model="documentSearch" placeholder="按文档名称搜索" /><el-select v-model="documentState"><el-option label="全部状态" value="all" /><el-option label="保留" value="active" /><el-option label="已逻辑删除" value="deleted" /></el-select><span>匹配 {{ filteredDocuments.length }} / {{ documents.length }}</span></div>
        <el-table :data="filteredDocuments"><el-table-column prop="title" label="文档" /><el-table-column prop="current_version_id" label="最新版本ID" /><el-table-column prop="visibility" label="访问范围" /><el-table-column label="状态"><template #default="{row}">{{ row.deleted ? '已逻辑删除' : '保留' }}</template></el-table-column>
          <el-table-column label="操作"><template #default="{row}"><el-button :disabled="busy" @click="openDocument(row)">版本 / 权限</el-button><el-button :disabled="busy || row.deleted" @click="removeDocument(row)">删除</el-button></template></el-table-column></el-table>
        <el-drawer v-model="documentDrawer" title="文档详情" size="min(760px, 100vw)"><template v-if="document"><h3>{{ document.title }} · 权限</h3><el-select v-model="documentVisibility"><el-option label="继承知识库" value="INHERIT" /><el-option label="仅管理员" value="ADMIN" /><el-option label="指定角色" value="ROLES" /></el-select>
          <el-select v-if="documentVisibility === 'ROLES'" v-model="documentRoles" multiple><el-option v-for="r in ['DISPATCHER','VIEWER']" :key="r" :value="r" /></el-select><el-button :disabled="busy" @click="savePermissions">保存文档权限</el-button></template>
        <el-table :data="versions"><el-table-column prop="version" label="版本" /><el-table-column prop="original_name" label="原始文件名" /><el-table-column prop="source_label" label="来源" /><el-table-column prop="created_at" label="创建时间" /><el-table-column prop="stage" label="处理状态" /><el-table-column prop="error_type" label="失败类型" /><el-table-column prop="sha256" label="内容摘要" show-overflow-tooltip /><el-table-column label="预览"><template #default="{row}"><el-button :disabled="busy" @click="readVersion(row)">查看文本</el-button></template></el-table-column></el-table>
        <pre v-if="versionText" class="evidence-panel">{{ versionText }}</pre></el-drawer>
      </el-tab-pane>
      <el-tab-pane label="Chunk预览" name="chunks" lazy>
        <div class="section-title"><h2>知识片段</h2><p>按索引检查实际切分内容。</p></div>
        <div class="toolbar"><el-select v-model="indexId" :disabled="busy" @change="chooseIndex"><el-option v-for="i in indexes" :key="i.id" :label="`#${i.id} ${i.status}`" :value="i.id" /></el-select><el-button :disabled="busy || !indexId" @click="previewChunks">读取Chunk</el-button><el-button :disabled="busy || !chunkOffset" @click="pageChunks(-50)">上一页</el-button><el-button :disabled="busy || chunkTotal === null || chunkOffset + chunks.length >= chunkTotal" @click="pageChunks(50)">下一页</el-button></div>
        <p>可见Chunk总数：{{ chunkTotal ?? '未读取' }} · 本页字符数：{{ chunkCharacters }}。Markdown/TXT按来源、章节与版本定位，不提供不存在的页码或Token估算。</p>
        <p>切分参数：{{ pretty(index?.configuration) }}</p>
        <el-input v-model="chunkSearch" placeholder="搜索当前Chunk页内容（不搜索其他分页）" /><p>本页匹配 {{ filteredChunks.length }} / {{ chunks.length }} 条</p>
        <el-table :data="filteredChunks"><el-table-column prop="chunk_id" label="稳定ID" width="200" show-overflow-tooltip /><el-table-column prop="document_version_id" label="文档版本ID" /><el-table-column prop="char_count" label="字符数" /><el-table-column prop="content" label="内容摘要" min-width="190" show-overflow-tooltip />
          <el-table-column label="操作" width="110"><template #default="{row}"><el-button text type="primary" @click="chunkDetail = row">查看内容</el-button></template></el-table-column></el-table>
        <el-drawer :model-value="!!chunkDetail" title="知识片段详情" size="min(680px, 100vw)" @close="chunkDetail = undefined">
          <template v-if="chunkDetail"><p>文档版本 #{{ chunkDetail.document_version_id }} · {{ chunkDetail.char_count }} 字符</p><p>{{ chunkDetail.chunk_id }}</p>
            <pre class="evidence-panel">{{ chunkDetail.content }}</pre><details><summary>来源与元数据</summary><pre>{{ pretty(chunkDetail.metadata) }}</pre></details></template>
        </el-drawer>
      </el-tab-pane>
      <el-tab-pane label="索引管理" name="indexes" lazy>
        <div class="section-title"><h2>构建与版本</h2><p>追踪构建任务、核对版本差异并切换活动索引。</p></div>
        <el-button :disabled="busy || !base || base.status !== 'ACTIVE'" @click="createBuild">创建构建任务</el-button>
        <el-table :data="jobs"><el-table-column prop="id" label="任务" /><el-table-column prop="status" label="状态" /><el-table-column prop="stage" label="当前 / 失败阶段" /><el-table-column label="完成阶段"><template #default="{row}">{{ row.progress?.completed_steps ?? '—' }}/{{ row.progress?.total_steps ?? '—' }}</template></el-table-column><el-table-column prop="started_at" label="开始时间" /><el-table-column prop="finished_at" label="结束时间" /><el-table-column prop="error_type" label="失败类型" /><el-table-column prop="failure_message" label="失败说明" /><el-table-column label="尝试"><template #default="{row}">{{ row.attempts }}/{{ row.max_attempts }}</template></el-table-column><el-table-column label="操作"><template #default="{row}"><el-button :disabled="busy" @click="jobId = row.id">详情</el-button><el-button :disabled="busy || row.status !== 'QUEUED'" @click="runBuild(row)">执行构建</el-button><el-button :disabled="busy || row.status !== 'FAILED' || !row.retryable || row.attempts >= row.max_attempts" @click="retryBuild(row)">安全重试入队</el-button><el-button :disabled="busy || row.status !== 'RUNNING'" @click="recoverBuild(row)">核验过期租约</el-button></template></el-table-column></el-table>
        <template v-if="selectedJob"><h3>构建记录 · #{{ selectedJob.id }}</h3><p>阶段步数只表示处理流程，不表示耗时百分比；旧记录缺少时间时显示为空。</p><el-table :data="selectedJob.timeline ?? []"><el-table-column prop="action" label="事件" /><el-table-column prop="stage" label="阶段" /><el-table-column prop="attempt" label="第几次尝试" /><el-table-column prop="created_at" label="时间" /></el-table></template>
        <p>历史索引保留，不自动清理；退役只停用非活动版本，文件和审计继续保留。</p>
        <el-table :data="indexes" highlight-current-row @current-change="(row: KnowledgeIndex | null) => { if(!busy && row) { indexId = row.id; chooseIndex() } }"><el-table-column prop="id" label="索引ID" /><el-table-column prop="status" label="状态" /><el-table-column prop="version" label="不可变版本" show-overflow-tooltip /><el-table-column prop="embedding_model" label="模型" /><el-table-column prop="model_revision" label="模型版本" show-overflow-tooltip /><el-table-column prop="dimension" label="维度" /><el-table-column prop="published_at" label="发布时间" /></el-table>
        <div class="toolbar"><span>当前选择 #{{ indexId ?? '—' }}</span><el-button :disabled="busy || !index" @click="compareIndex">查看新旧差异</el-button><el-button :disabled="busy || !index || index.status !== 'VALIDATED'" @click="publish(false)">人工发布</el-button><el-button :disabled="busy || !index || index.status !== 'PUBLISHED' || index.id === base?.active_index_id" @click="publish(true)">回退此已验证版本</el-button><el-button :disabled="busy || !index || index.id === base?.active_index_id || index.status === 'RETIRED'" @click="retire">退役非活动索引</el-button></div>
        <section v-if="diff" class="evidence-panel">
          <h3>索引差异 · #{{ diff.active_index_id ?? '无活动索引' }} → #{{ diff.candidate_index_id }}</h3>
          <div class="overview-grid">
            <article><small>新增文档</small><strong>{{ diff.added_documents.length }}</strong></article>
            <article><small>更新文档</small><strong>{{ diff.updated_documents.length }}</strong></article>
            <article><small>移除文档</small><strong>{{ diff.removed_documents.length }}</strong></article>
            <article><small>模型配置变更</small><strong>{{ diff.model_changed ? '是' : '否' }}</strong></article>
          </div>
          <details><summary>查看差异证据</summary><pre>{{ pretty(diff) }}</pre></details>
          <details v-if="index"><summary>查看选定索引配置</summary><pre>{{ pretty(index.configuration) }}</pre></details>
        </section>
        <KnowledgeVersionCompare v-if="indexes.length" :key="baseId"
          :indexes="indexes" :documents="documents" :runs="evaluations" :active-id="base?.active_index_id"
          @run="inspectEvaluation" />
      </el-tab-pane>
      <el-tab-pane label="检索实验室" name="lab" lazy>
        <div class="section-title"><h2>检索实验室</h2><p>按策略观察召回、融合和最终排序。</p></div>
        <p>只返回授权证据，不生成答案；排序分数不是事实置信度。</p>
        <div class="toolbar"><el-input v-model="query" placeholder="输入物流规则问题" maxlength="500" /><el-select v-model="strategy"><el-option v-for="m in ['vector','bm25','hybrid']" :key="m" :value="m" /></el-select><el-input-number v-model="topK" :min="1" :max="10" /><el-checkbox v-model="candidatePreview">预览当前选择的候选索引（管理员）</el-checkbox><el-button :disabled="busy || !base" @click="search">检索</el-button></div>
        <template v-if="result"><el-alert :title="result.refusal_reason ?? '仅有候选证据，是否足以回答尚未判定'" :type="result.results.length ? 'warning' : 'info'" :closable="false" /><p>{{ result.scope }} · {{ result.evidence_status }} · 生成 {{ result.generation }}</p>
          <div class="overview-grid" aria-label="本次检索阶段"><article v-for="stage in retrievalStages" :key="stage.label">
            <small>{{ stage.label }}</small><strong>{{ stage.value }}</strong>
          </article></div><details><summary>检索过程与配置</summary><pre>{{ pretty(result.stats) }}</pre></details>
          <el-table :data="result.candidates"><el-table-column prop="source" label="来源" /><el-table-column prop="section" label="章节" /><el-table-column prop="vector_rank" label="向量排名" /><el-table-column prop="bm25_rank" label="BM25排名" /><el-table-column prop="fusion_rank" label="融合排名" /><el-table-column prop="final_rank" label="最终排名" /><el-table-column prop="score" label="向量相似度" /><el-table-column prop="bm25_score" label="BM25分数" /><el-table-column prop="rrf_score" label="RRF分数" /><el-table-column v-if="result.candidates.some(row => row.reranker_score != null)" prop="reranker_score" label="精排分数" /></el-table>
          <article v-for="c in result.results" :key="c.chunk_id"><h3>{{ c.source }} · {{ c.section }}</h3><pre>{{ c.content }}</pre><small>文档版本 {{ c.document_id }} · Chunk {{ c.chunk_id }} · 索引 {{ c.index_version }}</small></article>
        </template>
      </el-tab-pane>
      <el-tab-pane label="评测中心" name="evaluations" lazy>
        <KnowledgeEvaluationAnalysis v-if="tab === 'evaluations'" :key="baseId" :runs="evaluations" :indexes="indexes"
          :selected="evaluationId" @select="evaluationId = $event" />
        <details class="run-controls">
          <summary>运行选定索引评测</summary>
          <p>文档自检固定使用 BM25。开发集与固定集已公开。向量或混合检索可能调用已配置的模型。</p>
          <div class="toolbar">
            <el-select v-model="indexId" aria-label="评测索引" :disabled="busy" placeholder="选择索引" @change="chooseIndex">
              <el-option v-for="i in indexes" :key="i.id" :label="`#${i.id} ${i.status}`" :value="i.id" />
            </el-select>
            <el-select v-model="dataset" aria-label="评测集"><el-option label="文档自检（BM25）" value="document_smoke" /><el-option label="30题开发集" value="development" /><el-option label="12题固定集" value="fixed" /></el-select>
            <el-select v-if="dataset !== 'document_smoke'" v-model="evaluationStrategy" aria-label="评测策略"><el-option v-for="m in ['vector','bm25','hybrid']" :key="m" :value="m" /></el-select>
            <el-button type="primary" :loading="busy" :disabled="!index || index.status === 'RETIRED'" @click="validate">运行评测</el-button>
          </div>
        </details>
      </el-tab-pane>
      <el-tab-pane label="运行监控" name="monitor" lazy>
        <div class="section-title"><h2>运行监控</h2><p>查看已记录的检索和构建活动。</p></div><p>调用次数与成本范围按实际任务记录展示；UNKNOWN不代表0，预算预留不代表供应商账单。</p><pre>{{ pretty(metrics) }}</pre><el-table :data="jobs"><el-table-column prop="id" label="任务" /><el-table-column prop="duration_ms" label="处理毫秒" /><el-table-column prop="model_calls" label="向量处理批次" /><el-table-column prop="cost" label="成本范围" /><el-table-column prop="error_type" label="错误类型" /></el-table></el-tab-pane>
      <el-tab-pane label="审计管理" name="audits" lazy>
        <div class="section-title"><h2>审计管理</h2><p>查看操作元数据和历史结果。</p></div><p>仅展示操作元数据，不记录完整查询、文档正文或模型凭据。</p><el-table :data="audits"><el-table-column prop="username" label="操作人" /><el-table-column prop="created_at" label="时间" /><el-table-column prop="action" label="操作" /><el-table-column prop="object_type" label="目标类型" /><el-table-column prop="object_id" label="目标ID" /><el-table-column label="结果与失败原因"><template #default="{row}"><pre>{{ pretty(row.changes) }}</pre></template></el-table-column></el-table></el-tab-pane>
    </el-tabs>
      </div>
    </div>
  </section>
</template>

<style scoped>
:global(html:has(.knowledge-page)),
:global(body:has(.knowledge-page)),
:global(#app:has(.knowledge-page)) { min-width: 0; }
.knowledge-page { --rag-accent: #4948bc; --rag-border: #dfe5ef; --el-color-primary: #4948bc; display: grid; gap: 16px; color: #19243b; }
.rag-heading { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
.rag-heading p, .section-title p, small { color: #56647a; margin: 0 0 5px; }
.rag-heading h1, .section-title h2 { margin: 0; }
.header-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.rag-heading a { color: var(--rag-accent); }
.rag-layout { display: grid; grid-template-columns: 174px minmax(0, 1fr); gap: 16px; align-items: start; }
.rag-nav, .rag-content { background: white; border: 1px solid var(--rag-border); border-radius: 12px; min-width: 0; }
.rag-nav { position: sticky; top: 76px; display: grid; gap: 12px; padding: 12px; }
.rag-nav p { padding: 0 8px; margin: 0 0 4px; color: #56647a; font-size: 12px; font-weight: 600; }
.rag-nav button { display: block; width: 100%; text-align: start; border: 0; background: transparent; border-radius: 8px; padding: 8px; cursor: pointer; color: inherit; font: inherit; }
.rag-nav button:hover, .rag-nav button[aria-current] { color: var(--rag-accent); background: #edeeff; }
.rag-content { padding: clamp(12px, 2vw, 24px); }
.rag-tabs :deep(> .el-tabs__header) { display: none; }
.section-title { margin-bottom: 18px; }
.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 10px 0; }
.toolbar .el-input { max-width: 340px; }
.el-select { width: 180px; max-width: 100%; }
.el-form { max-width: 700px; margin: 20px 0; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 420px; overflow: auto; }
article, .evidence-panel, .run-controls { border: 1px solid var(--rag-border); border-radius: 12px; padding: 14px; margin-top: 12px; }
.run-controls { background: #f8f9fe; }
summary { cursor: pointer; }
.overview-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr)); gap: 12px; }
.overview-grid article { background: #f8f9fe; margin-top: 0; }
.overview-panels { margin-top: 12px; }
.overview-panels h3, .overview-panels p { margin: 0 0 6px; overflow-wrap: anywhere; }
.summary-fields { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 12px; font-size: 13px; }
.summary-fields dt { color: #56647a; }
.summary-fields dd { margin: 0; overflow-wrap: anywhere; }
.activity-list { list-style: none; padding: 0; }
.activity-list li { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px 12px; padding: 8px 0; border-bottom: 1px solid var(--rag-border); overflow-wrap: anywhere; }
.activity-list li span:last-child { color: #56647a; font-size: 13px; }
.overview-grid strong { display: block; font-size: 21px; margin-top: 4px; }
small { overflow-wrap: anywhere; }
@media (max-width: 1060px) {
  .rag-layout { grid-template-columns: minmax(0, 1fr); }
  .rag-nav { position: static; display: flex; flex-wrap: wrap; }
  :global(.admin-layout:has(.knowledge-page) .app-header) { min-height: 64px; height: auto; flex-wrap: wrap; gap: 6px; padding: 6px 12px; }
}
@media (max-width: 640px) {
  :global(.admin-layout:has(.knowledge-page) .admin-layout__body) { margin-left: 72px; }
  :global(.admin-layout:has(.knowledge-page) .admin-layout__main) { padding: 12px; }
  :global(.admin-layout:has(.knowledge-page) .app-header) { z-index: 40; }
  :global(.admin-layout:has(.knowledge-page) .app-header__right) { flex-wrap: wrap; }
}
</style>
