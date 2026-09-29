<script setup lang="ts">
import { ChatDotRound, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, nextTick, onMounted, ref } from 'vue'

import {
  createConversation,
  getConversation,
  listConversations,
  sendConversationMessage,
} from '@/api/agent'
import type { AgentConversation, AgentConversationDetail } from '@/types/agent'
import AgentComposer from '@/views/agent/components/AgentComposer.vue'
import AgentConversationList from '@/views/agent/components/AgentConversationList.vue'
import AgentMessageList from '@/views/agent/components/AgentMessageList.vue'

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
const detailRequestSequence = ref(0)
const messageListRef = ref<MessageListExpose | null>(null)

const interactionLocked = computed(() => creating.value || sending.value)
const messages = computed(() => currentConversation.value?.messages ?? [])

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
  currentConversationId.value = conversationId
  currentConversation.value = null
  conversationLoading.value = true
  try {
    const response = await getConversation(conversationId)
    if (
      requestSequence !== detailRequestSequence.value ||
      currentConversationId.value !== conversationId
    ) return
    currentConversation.value = response.data
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
    conversations.value = [created, ...conversations.value.filter((item) => item.id !== created.id)]
    currentConversationId.value = created.id
    currentConversation.value = { ...created, messages: [] }
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
  if (!message || message.length > 4000 || sending.value || creating.value) return

  let conversationId = currentConversationId.value
  if (conversationId === null) {
    conversationId = await createAndSelectConversation()
    if (conversationId === null) return
  }

  sending.value = true
  const requestSequence = ++detailRequestSequence.value
  try {
    await sendConversationMessage(conversationId, message)
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
      input.value = ''
      await messageListRef.value?.scrollToBottom()
    }
  } catch {
    // The backend stores no half exchange; keep the input so the user can retry.
  } finally {
    sending.value = false
  }
}

async function initialize() {
  await refreshConversationList()
  const firstConversation = conversations.value[0]
  if (firstConversation) await selectConversation(firstConversation.id)
}

onMounted(initialize)
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
        @click="refreshConversationList"
      >
        刷新会话
      </el-button>
    </div>

    <el-alert
      title="当前为只读调度助手，不会修改派车方案、配送需求或配送状态。"
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
            <span>物流业务只读查询</span>
          </div>
          <el-tag type="success" effect="plain">只读</el-tag>
        </div>

        <AgentMessageList
          ref="messageListRef"
          :messages="messages"
          :loading="conversationLoading"
          :responding="sending"
          :has-conversation="currentConversationId !== null"
        />
        <AgentComposer v-model="input" :sending="interactionLocked" @send="sendMessage" />
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
