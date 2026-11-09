<script setup lang="ts">
import { ChatDotRound, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onMounted, onBeforeUnmount, ref } from 'vue'

import {
  createConversation,
  getConversation,
  listConversations,
  sendConversationMessage,
  confirmPendingAction,
  cancelPendingAction,
  getAgentExecutions,
  resumeAgentExecution,
  cancelAgentExecution,
} from '@/api/agent'
import type { AgentConversation, AgentConversationDetail, AgentPendingAction, AgentExecutionReport } from '@/types/agent'
import { useAuthStore } from '@/stores/auth'
import AgentComposer from '@/views/agent/components/AgentComposer.vue'
import AgentConversationList from '@/views/agent/components/AgentConversationList.vue'
import AgentMessageList from '@/views/agent/components/AgentMessageList.vue'
import AgentExecutionPanel from '@/views/agent/components/AgentExecutionPanel.vue'

interface MessageListExpose {
  scrollToBottom: () => Promise<void>
}

const conversations = ref<AgentConversation[]>([])
const currentConversation = ref<AgentConversationDetail | null>(null)
const currentConversationId = ref<number | null>(null)
const input = ref('')
const listLoading = ref(false)
const conversationLoading = ref(false)
const creating = ref(false)
const sending = ref(false)
const liveAnswer = ref('')
const liveStatus = ref('')
const liveTrace = ref('')
const liveMetrics = ref<Record<string, unknown> | null>(null)
let streamAbort: AbortController | null = null
async function stopStream() {
  if (currentConversationId.value === null) return
  const { default: http } = await import('@/api/http')
  await http.post(`/agent/conversations/${currentConversationId.value}/stream/cancel`)
  liveStatus.value = '已请求取消，等待服务端确认'
}
const detailRequestSequence = ref(0)
const messageListRef = ref<MessageListExpose | null>(null)
const actionLoadingId = ref<number | null>(null)
const authStore = useAuthStore()
const executions = ref<AgentExecutionReport[]>([])
const resumeLoadingId = ref<string | null>(null)
const cancelLoadingId = ref<string | null>(null)
const cancellationNotice = ref('')
const cancellationExecutionId = ref<string | null>(null)
const cancellationDisplay = computed(() => executions.value[0]?.execution_id !== cancellationExecutionId.value ? ''
  : executions.value.some(item => item.execution_id === cancellationExecutionId.value && item.status === 'CANCELLED')
    ? '后端已确认当前执行取消。' : cancellationNotice.value)
const executionStatusError = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let pollGeneration = 0
let pollingConversationId: number | null = null

const activeExecutionStates = new Set(['RUNNING', 'RECOVERING', 'RETRYING'])

function mergeExecutionReports(incoming: AgentExecutionReport[]) {
  const known = new Map(executions.value.map(item => [item.execution_id, item]))
  const accepted = incoming.map(item => {
    const previous = known.get(item.execution_id)
    if (!previous) return item
    const revision = item.revision ?? 0
    const previousRevision = previous.revision ?? 0
    if (revision !== previousRevision) return revision > previousRevision ? item : previous
    // Older checkpoints have no revision; preserve progress and terminal states.
    if (previous.events.length !== item.events.length) {
      return previous.events.length > item.events.length ? previous : item
    }
    return !activeExecutionStates.has(previous.status) && activeExecutionStates.has(item.status) ? previous : item
  })
  const ids = new Set(accepted.map(item => item.execution_id))
  const missing = executions.value.filter(item => !ids.has(item.execution_id))
  const latest = executions.value[0]?.execution_id
  const head = accepted[0]?.execution_id
  // A poll started before a new execution may omit it completely. Preserve the
  // known newer head, while allowing a genuinely new server execution to lead.
  const olderList = latest && !ids.has(latest) && head && known.has(head)
  executions.value = (olderList ? [...missing, ...accepted] : [...accepted, ...missing]).slice(0, 20)
}

function stopExecutionPolling() {
  ++pollGeneration
  clearTimeout(pollTimer)
  pollingConversationId = null
}

function needsExecutionPolling() {
  const current = executions.value[0]
  return sending.value || resumeLoadingId.value !== null ||
    (!!current && activeExecutionStates.has(current.status) && current.can_resume !== true)
}

function ensureExecutionPolling(id: number) {
  if (disposed || currentConversationId.value !== id || !needsExecutionPolling() || pollingConversationId === id) return
  pollingConversationId = id
  const generation = ++pollGeneration
  void pollExecution(id, generation)
}

async function refreshExecutions(id: number) {
  try {
    const response = await getAgentExecutions(id)
    if (!disposed && currentConversationId.value === id) {
      mergeExecutionReports(response.data)
      executionStatusError.value = false
    }
  } catch {
    if (!disposed && currentConversationId.value === id) executionStatusError.value = true
  }
}

async function pollExecution(id: number, generation: number) {
  await refreshExecutions(id)
  if (disposed || generation !== pollGeneration || currentConversationId.value !== id) return
  if (needsExecutionPolling()) {
    pollTimer = setTimeout(() => { void pollExecution(id, generation) }, 1000)
  } else {
    pollingConversationId = null
  }
}

const interactionLocked = computed(() => creating.value || sending.value || actionLoadingId.value !== null || resumeLoadingId.value !== null || cancelLoadingId.value !== null)
const serverExecutionActive = computed(() => {
  const current = executions.value[0]
  return !!current && activeExecutionStates.has(current.status) && current.can_resume !== true
})
const sendBlocked = computed(() => interactionLocked.value || serverExecutionActive.value)
const messages = computed(() => currentConversation.value?.messages ?? [])
const pendingActions = computed(() => currentConversation.value?.pending_actions ?? [])

async function refreshConversationList() {
  listLoading.value = true
  try {
    const response = await listConversations({ offset: 0, limit: 100 })
    conversations.value = response.data
  } catch {
    // The shared Axios interceptor displays a safe message.
  } finally {
    listLoading.value = false
  }
}

async function selectConversation(conversationId: number) {
  if (interactionLocked.value || conversationId === currentConversationId.value) return
  const requestSequence = ++detailRequestSequence.value
  stopExecutionPolling()
  currentConversationId.value = conversationId
  currentConversation.value = null
  executions.value = []
  executionStatusError.value = false
  conversationLoading.value = true
  try {
    const response = await getConversation(conversationId)
    if (
      requestSequence !== detailRequestSequence.value ||
      currentConversationId.value !== conversationId
    ) return
    currentConversation.value = response.data
    await refreshExecutions(conversationId)
    ensureExecutionPolling(conversationId)
    await messageListRef.value?.scrollToBottom()
  } catch {
    if (requestSequence === detailRequestSequence.value) currentConversation.value = null
  } finally {
    if (requestSequence === detailRequestSequence.value) conversationLoading.value = false
  }
}

async function createAndSelectConversation(): Promise<number | null> {
  if (interactionLocked.value) return null
  creating.value = true
  try {
    const response = await createConversation()
    const created = response.data
    stopExecutionPolling()
    conversations.value = [created, ...conversations.value.filter((item) => item.id !== created.id)]
    currentConversationId.value = created.id
    currentConversation.value = { ...created, messages: [], pending_actions: [] }
    executions.value = []
    executionStatusError.value = false
    ++detailRequestSequence.value
    await nextTick()
    return created.id
  } catch {
    return null
  } finally {
    creating.value = false
  }
}

async function handleCreateConversation() {
  const conversationId = await createAndSelectConversation()
  if (conversationId !== null) ElMessage.success('新会话已创建')
}

async function sendMessage() {
  const message = input.value.trim()
  if (!message || message.length > 4000 || sendBlocked.value) return

  let conversationId = currentConversationId.value
  if (conversationId === null) {
    conversationId = await createAndSelectConversation()
    if (conversationId === null) return
  }

  sending.value = true
  ensureExecutionPolling(conversationId)
  const requestSequence = ++detailRequestSequence.value
  try {
      liveAnswer.value = ''; liveStatus.value = '正在启动'; liveMetrics.value = null
      streamAbort = new AbortController()
      const executionResponse = await sendConversationMessage(conversationId, message, event => {
        liveTrace.value = event.trace_id
        if (event.event_type === 'token') liveAnswer.value += event.payload.text
        if (event.event_type === 'message_complete') { liveAnswer.value = event.payload.content; liveStatus.value = '已完成' }
        if (event.event_type === 'agent_status') liveStatus.value = `执行状态：${event.payload.status}`
        if (event.event_type === 'tool_call_start') liveStatus.value = `正在调用工具：${event.payload.tool || ''}`
        if (event.event_type === 'tool_call_result') liveStatus.value = `工具执行：${event.payload.status}`
        if (event.event_type === 'memory_retrieval') liveStatus.value = `已召回 ${event.payload.count} 条记忆`
        if (event.event_type === 'model_metrics') liveMetrics.value = event.payload
        if (event.event_type === 'error') liveStatus.value = event.payload.message
        if (event.event_type === 'cancelled') liveStatus.value = '任务已取消，请核对执行记录'
        if (event.event_type === 'approval_required') liveStatus.value = '等待人工审批'
      }, streamAbort.signal)
    if (executionResponse?.data?.execution && currentConversationId.value === conversationId) {
      mergeExecutionReports([executionResponse.data.execution])
    }
    const [detailResponse, listResponse] = await Promise.all([
      getConversation(conversationId),
      listConversations({ offset: 0, limit: 100 }),
    ])
    conversations.value = listResponse.data
    if (
      currentConversationId.value === conversationId &&
      requestSequence === detailRequestSequence.value
    ) {
      currentConversation.value = detailResponse.data
        liveAnswer.value = ''
      input.value = ''
      await messageListRef.value?.scrollToBottom()
    }
  } catch {
    // The backend stores no half exchange; keep the input so the user can retry.
  } finally {
      streamAbort = null
    sending.value = false
    stopExecutionPolling()
    await refreshExecutions(conversationId)
    ensureExecutionPolling(conversationId)
  }
}

async function initialize() {
  await refreshConversationList()
  const firstConversation = conversations.value[0]
  if (firstConversation) await selectConversation(firstConversation.id)
}

async function reloadCurrentConversation(id = currentConversationId.value) {
  if (id === null) return
  const response = await getConversation(id)
  if (currentConversationId.value === id) currentConversation.value = response.data
  await refreshExecutions(id)
  ensureExecutionPolling(id)
}

async function refreshCurrentStatus() {
  await refreshConversationList()
  if (currentConversationId.value === null) return
  try {
    await reloadCurrentConversation()
  } catch {
    executionStatusError.value = true
  }
}

async function handleCancelExecution(execution: AgentExecutionReport) {
  const conversationId = currentConversationId.value
  const actual = executions.value.find(item => item.execution_id === execution.execution_id)
  if (conversationId === null || cancelLoadingId.value !== null || actionLoadingId.value !== null || resumeLoadingId.value !== null ||
      !actual || !activeExecutionStates.has(actual.status) || actual.can_resume === true) return
  cancelLoadingId.value = execution.execution_id
  cancellationExecutionId.value = execution.execution_id
  try {
    await cancelAgentExecution(conversationId, execution.execution_id)
    cancellationNotice.value = '取消请求已送达，正在等待后端停止和清理；尚未确认取消完成。'
  } catch {
    cancellationNotice.value = '取消结果尚未核实，请刷新查看；不会自动重复提交。'
  } finally {
    cancelLoadingId.value = null
    await refreshExecutions(conversationId)
    ensureExecutionPolling(conversationId)
  }
}

async function handleResumeExecution(execution: AgentExecutionReport) {
  const conversationId = currentConversationId.value
  const authoritative = executions.value.find(item => item.execution_id === execution.execution_id)
  if (conversationId === null || interactionLocked.value || authoritative?.can_resume !== true) return
  resumeLoadingId.value = execution.execution_id
  ensureExecutionPolling(conversationId)
  try {
    const response = await resumeAgentExecution(conversationId, execution.execution_id)
    if (!disposed && currentConversationId.value === conversationId) mergeExecutionReports([response.data])
    await reloadCurrentConversation(conversationId)
  } catch {
    // The response may have been lost after a completed step. Reconcile once;
    // only a later explicit action can ask the backend to resume again.
    await reconcileAction(conversationId)
  } finally {
    resumeLoadingId.value = null
    stopExecutionPolling()
    await refreshExecutions(conversationId)
    ensureExecutionPolling(conversationId)
  }
}

async function reconcileAction(conversationId: number) {
  // A timeout does not prove the write failed. Read authoritative state;
  // never replay confirmation automatically.
  try {
    await reloadCurrentConversation(conversationId)
  } catch {
    // Shared interceptor reports network failure; preserve the visible history.
  }
}

async function handleConfirmAction(action: AgentPendingAction) {
  const conversationId = currentConversationId.value
  if (conversationId === null || interactionLocked.value || !authStore.canOperate || action.status !== 'PENDING') return
  actionLoadingId.value = action.id
  try {
    await ElMessageBox.confirm(
      action.risk_level === 'HIGH' ? `${action.summary}。该操作风险较高，确认继续？` : `${action.summary}，确认执行？`,
      '确认 Agent 写操作',
      { type: action.risk_level === 'HIGH' ? 'error' : 'warning', confirmButtonText: '确认执行', cancelButtonText: '返回' },
    )
    await confirmPendingAction(conversationId, action.id)
    ElMessage.success('操作已执行')
    await reloadCurrentConversation(conversationId)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    await reconcileAction(conversationId)
  } finally {
    actionLoadingId.value = null
  }
}

async function handleCancelAction(action: AgentPendingAction) {
  const conversationId = currentConversationId.value
  if (conversationId === null || interactionLocked.value || !authStore.canOperate || action.status !== 'PENDING') return
  actionLoadingId.value = action.id
  try {
    await cancelPendingAction(conversationId, action.id)
    ElMessage.success('待确认操作已取消，业务数据未修改')
    await reloadCurrentConversation(conversationId)
  } catch {
    // Shared interceptor displays the backend business error.
    await reconcileAction(conversationId)
  } finally {
    actionLoadingId.value = null
  }
}

onMounted(initialize)
onBeforeUnmount(() => { disposed = true; streamAbort?.abort(); stopExecutionPolling() })
</script>

<template>
  <section class="agent-page">
    <div class="agent-heading">
      <div>
        <p class="agent-heading__eyebrow">AI AGENT</p>
        <h1><el-icon><ChatDotRound /></el-icon>智能调度助手</h1>
      </div>
      <el-button
        :icon="Refresh"
        :loading="listLoading || conversationLoading"
        :disabled="interactionLocked"
        @click="refreshCurrentStatus"
      >
        刷新会话
      </el-button>
    </div>

    <el-alert
      title="助手可查询业务数据，也可生成待确认写操作；只有点击确认卡片后才会真正执行。"
      type="info"
      :closable="false"
      show-icon
      class="readonly-alert"
    />

    <div class="agent-workspace">
      <AgentConversationList
        :conversations="conversations"
        :current-conversation-id="currentConversationId"
        :loading="listLoading"
        :disabled="interactionLocked"
        @create="handleCreateConversation"
        @select="selectConversation"
      />

      <main class="chat-panel">
        <div class="chat-panel__header">
          <div>
            <strong>{{ currentConversation?.title ?? '新会话' }}</strong>
            <span>物流查询与安全确认操作</span>
          </div>
          <el-tag type="success" effect="plain">确认后执行</el-tag>
        </div>

        <AgentMessageList
          ref="messageListRef"
          :messages="messages"
          :loading="conversationLoading"
          :responding="sending"
          :has-conversation="currentConversationId !== null"
          :pending-actions="pendingActions"
          :action-loading-id="actionLoadingId"
          :can-operate="authStore.canOperate"
          @confirm-action="handleConfirmAction"
          @cancel-action="handleCancelAction"
        />
        <p v-if="cancellationDisplay" role="status">{{ cancellationDisplay }}</p>
        <AgentExecutionPanel :executions="executions" :resume-loading-id="resumeLoadingId" :cancel-pending="cancelLoadingId !== null"
          :disabled="interactionLocked" :status-error="executionStatusError" @resume="handleResumeExecution" @cancel="handleCancelExecution" />
        <p v-if="serverExecutionActive" class="execution-pending" role="status">服务端仍在执行当前任务，状态确认前暂停发送新请求。</p>
        <p role="status">{{ liveStatus }}</p>
        <p v-if="liveAnswer" style="white-space: pre-wrap">{{ liveAnswer }}</p>
        <el-button v-if="sending" @click="stopStream">停止生成</el-button>
        <details v-if="liveTrace"><summary>执行详情</summary><p>追踪标识：{{ liveTrace }}</p><pre>{{ liveMetrics }}</pre></details>
        <AgentComposer v-model="input" :sending="sendBlocked" @send="sendMessage" />
      </main>
    </div>
  </section>
</template>

<style scoped>
.agent-page {
  max-width: 1540px;
  margin: 0 auto;
}

.agent-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.agent-heading__eyebrow {
  margin: 0 0 6px;
  color: #2f80ed;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 1.2px;
}

.agent-heading h1 {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0;
  color: #172b4d;
  font-size: 27px;
}

.readonly-alert {
  margin-bottom: 14px;
  border-radius: 10px;
}

.agent-workspace {
  display: grid;
  height: calc(100vh - 218px);
  min-height: 500px;
  grid-template-columns: 286px minmax(0, 1fr);
  overflow: hidden;
  background: #fff;
  border: 1px solid #e4eaf2;
  border-radius: 16px;
  box-shadow: 0 8px 28px rgba(23, 43, 77, 0.06);
}

.chat-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
}

.execution-pending { margin: 8px 18px 0; color: #64748b; font-size: 12px; }

.chat-panel__header {
  display: flex;
  min-height: 72px;
  align-items: center;
  justify-content: space-between;
  padding: 13px 20px;
  background: #fff;
  border-bottom: 1px solid #e4eaf2;
}

.chat-panel__header > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.chat-panel__header strong {
  overflow: hidden;
  color: #172b4d;
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-panel__header span {
  color: #8993a4;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .agent-workspace {
    grid-template-columns: 250px minmax(0, 1fr);
  }
}
</style>
