<script setup lang="ts">
import { ChatDotRound, User } from '@element-plus/icons-vue'
import { nextTick, ref } from 'vue'

import type { AgentConversationMessage, AgentPendingAction } from '@/types/agent'
import AgentPendingActionCard from './AgentPendingActionCard.vue'

defineProps<{
  messages: AgentConversationMessage[]
  loading: boolean
  responding: boolean
  hasConversation: boolean
  pendingActions: AgentPendingAction[]
  actionLoadingId: number | null
  canOperate: boolean
}>()

defineEmits<{
  confirmAction: [action: AgentPendingAction]
  cancelAction: [action: AgentPendingAction]
}>()

const scrollContainer = ref<HTMLElement | null>(null)

async function scrollToBottom() {
  await nextTick()
  const element = scrollContainer.value
  if (element) element.scrollTop = element.scrollHeight
}

defineExpose({ scrollToBottom })
</script>

<template>
  <div ref="scrollContainer" v-loading="loading" class="message-list">
    <div v-if="!loading && messages.length === 0 && !responding" class="message-list__empty">
      <div class="assistant-mark"><ChatDotRound /></div>
      <h2>{{ hasConversation ? '开始询问调度信息' : '开始一个新的智能调度会话' }}</h2>
      <p>你可以询问：</p>
      <ul>
        <li>今天有哪些配送需求？</li>
        <li>今天哪些车辆出勤？</li>
        <li>某个派车方案有哪些未分配需求？</li>
        <li>当前方案能否发布？</li>
      </ul>
    </div>

    <div v-else class="message-list__content">
      <article
        v-for="message in messages"
        :key="message.id"
        class="message-row"
        :class="message.role === 'USER' ? 'is-user' : 'is-assistant'"
      >
        <div class="message-row__avatar">
          <el-icon><User v-if="message.role === 'USER'" /><ChatDotRound v-else /></el-icon>
        </div>
        <div class="message-row__body">
          <span>{{ message.role === 'USER' ? '你' : '智能调度助手' }}</span>
          <div class="message-bubble">{{ message.content }}</div>
        </div>
      </article>

      <AgentPendingActionCard
        v-for="action in pendingActions"
        :key="`action-${action.id}`"
        :action="action"
        :loading="actionLoadingId === action.id"
        :can-operate="canOperate"
        @confirm="$emit('confirmAction', $event)"
        @cancel="$emit('cancelAction', $event)"
      />

      <article v-if="responding" class="message-row is-assistant">
        <div class="message-row__avatar"><el-icon><ChatDotRound /></el-icon></div>
        <div class="message-row__body">
          <span>智能调度助手</span>
          <div class="message-bubble is-loading">
            <i></i><i></i><i></i>
            正在查询...
          </div>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 28px clamp(24px, 5vw, 72px);
  background: #f8fafc;
}

.message-list__empty {
  max-width: 560px;
  margin: 70px auto 0;
  color: #6b778c;
  text-align: center;
}

.assistant-mark {
  display: grid;
  width: 58px;
  height: 58px;
  margin: 0 auto 16px;
  color: #fff;
  background: linear-gradient(135deg, #2f80ed, #1d66c2);
  border-radius: 18px;
  box-shadow: 0 12px 28px rgba(47, 128, 237, 0.24);
  place-items: center;
}

.assistant-mark svg {
  width: 28px;
  height: 28px;
}

.message-list__empty h2 {
  margin: 0 0 10px;
  color: #172b4d;
  font-size: 21px;
}

.message-list__empty p {
  margin: 0 0 12px;
}

.message-list__empty ul {
  display: inline-grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  text-align: left;
  list-style: none;
}

.message-list__empty li::before {
  margin-right: 8px;
  color: #2f80ed;
  content: '•';
}

.message-list__content {
  max-width: 920px;
  margin: 0 auto;
}

.message-row {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  margin-bottom: 22px;
}

.message-row.is-user {
  flex-direction: row-reverse;
}

.message-row__avatar {
  display: grid;
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  color: #fff;
  background: #2f80ed;
  border-radius: 10px;
  place-items: center;
}

.is-user .message-row__avatar {
  background: #52627a;
}

.message-row__body {
  display: flex;
  max-width: min(78%, 720px);
  flex-direction: column;
  gap: 5px;
}

.is-user .message-row__body {
  align-items: flex-end;
}

.message-row__body > span {
  color: #8993a4;
  font-size: 12px;
}

.message-bubble {
  padding: 11px 14px;
  color: #243b5a;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #fff;
  border: 1px solid #e4eaf2;
  border-radius: 4px 14px 14px;
  box-shadow: 0 3px 12px rgba(23, 43, 77, 0.05);
}

.is-user .message-bubble {
  color: #fff;
  background: #2f80ed;
  border-color: #2f80ed;
  border-radius: 14px 4px 14px 14px;
}

.message-bubble.is-loading {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #6b778c;
}

.message-bubble.is-loading i {
  width: 5px;
  height: 5px;
  background: #2f80ed;
  border-radius: 50%;
}

.message-bubble.is-loading i:last-of-type {
  margin-right: 4px;
}
</style>
