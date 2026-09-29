import http from '@/api/http'
import type {
  AgentConversation,
  AgentConversationDetail,
  AgentSendMessageResponse,
  AgentStatelessChatResponse,
  AgentPendingActionExecutionResponse,
} from '@/types/agent'

// A tool loop can require more than one provider request. Keep this longer than
// the per-model-call backend timeout without changing other business API calls.
const AGENT_REQUEST_TIMEOUT_MS = 120_000

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
    { timeout: AGENT_REQUEST_TIMEOUT_MS },
  )
}

export function sendStatelessChat(message: string) {
  return http.post<AgentStatelessChatResponse>(
    '/agent/chat',
    { message },
    { timeout: AGENT_REQUEST_TIMEOUT_MS },
  )
}

export function confirmPendingAction(conversationId: number, actionId: number) {
  return http.post<AgentPendingActionExecutionResponse>(
    `/agent/conversations/${conversationId}/pending-actions/${actionId}/confirm`,
  )
}

export function cancelPendingAction(conversationId: number, actionId: number) {
  return http.post<AgentPendingActionExecutionResponse>(
    `/agent/conversations/${conversationId}/pending-actions/${actionId}/cancel`,
  )
}
