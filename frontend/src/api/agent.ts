import http from '@/api/http'
import type {
  AgentConversation,
  AgentConversationDetail,
  AgentSendMessageResponse,
  AgentStatelessChatResponse,
} from '@/types/agent'

export function createConversation() {
  return http.post<AgentConversation>('/agent/conversations')
}

export function listConversations(params: { offset?: number; limit?: number } = {}) {
  return http.get<AgentConversation[]>('/agent/conversations', { params })
}

export function getConversation(conversationId: number) {
  return http.get<AgentConversationDetail>(`/agent/conversations/${conversationId}`)
}

export function sendConversationMessage(conversationId: number, message: string) {
  return http.post<AgentSendMessageResponse>(
    `/agent/conversations/${conversationId}/messages`,
    { message },
  )
}

export function sendStatelessChat(message: string) {
  return http.post<AgentStatelessChatResponse>('/agent/chat', { message })
}
