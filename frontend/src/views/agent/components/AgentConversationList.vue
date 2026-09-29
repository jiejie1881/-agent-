<script setup lang="ts">
import { ChatDotRound, Plus } from '@element-plus/icons-vue'

import type { AgentConversation } from '@/types/agent'

defineProps<{
  conversations: AgentConversation[]
  currentConversationId: number | null
  loading: boolean
  disabled: boolean
}>()

const emit = defineEmits<{
  create: []
  select: [conversationId: number]
}>()

function formatUpdatedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}
</script>

<template>
  <aside class="conversation-panel">
    <div class="conversation-panel__header">
      <div>
        <span>历史会话</span>
        <small>{{ conversations.length }} 个</small>
      </div>
      <el-button
        type="primary"
        :icon="Plus"
        :disabled="disabled"
        aria-label="新建会话"
        @click="emit('create')"
      >
        新建
      </el-button>
    </div>

    <el-scrollbar v-loading="loading" class="conversation-panel__body">
      <el-empty
        v-if="!loading && conversations.length === 0"
        description="暂无历史会话"
        :image-size="72"
      />
      <button
        v-for="conversation in conversations"
        :key="conversation.id"
        type="button"
        class="conversation-item"
        :class="{ 'is-active': conversation.id === currentConversationId }"
        :disabled="disabled"
        @click="emit('select', conversation.id)"
      >
        <el-icon><ChatDotRound /></el-icon>
        <span class="conversation-item__content">
          <strong>{{ conversation.title }}</strong>
          <small>{{ formatUpdatedAt(conversation.updated_at) }}</small>
        </span>
      </button>
    </el-scrollbar>
  </aside>
</template>

<style scoped>
.conversation-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
  background: #f8fafc;
  border-right: 1px solid #e4eaf2;
}

.conversation-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 72px;
  padding: 14px 16px;
  background: #fff;
  border-bottom: 1px solid #e4eaf2;
}

.conversation-panel__header > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.conversation-panel__header span {
  color: #172b4d;
  font-weight: 700;
}

.conversation-panel__header small {
  color: #8993a4;
}

.conversation-panel__body {
  flex: 1;
  min-height: 0;
  padding: 10px;
}

.conversation-item {
  display: flex;
  width: 100%;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 6px;
  padding: 12px;
  color: #52627a;
  text-align: left;
  background: transparent;
  border: 0;
  border-radius: 10px;
  cursor: pointer;
}

.conversation-item:hover:not(:disabled) {
  background: #edf4ff;
}

.conversation-item.is-active {
  color: #1d66c2;
  background: #e7f1ff;
}

.conversation-item:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.conversation-item .el-icon {
  flex: 0 0 auto;
  margin-top: 2px;
  font-size: 18px;
}

.conversation-item__content {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 5px;
}

.conversation-item__content strong {
  overflow: hidden;
  color: inherit;
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-item__content small {
  color: #8993a4;
  font-size: 11px;
}
</style>
