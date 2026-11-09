import http from '@/api/http'
import { readAgentStream, type AgentStreamEvent } from '@/utils/agentStream'
import type {
  AgentConversation,
  AgentConversationDetail,
  AgentSendMessageResponse,
  AgentStatelessChatResponse,
  AgentPendingActionExecutionResponse,
  AgentExecutionReport,
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

export function getAgentExecutions(conversationId: number) {
  return http.get<AgentExecutionReport[]>(`/agent/conversations/${conversationId}/executions`)
}

export function resumeAgentExecution(conversationId: number, executionId: string) {
  return http.post<AgentExecutionReport>(
    `/agent/conversations/${conversationId}/executions/${encodeURIComponent(executionId)}/resume`,
    undefined,
    { timeout: AGENT_REQUEST_TIMEOUT_MS },
  )
}

export function cancelAgentExecution(conversationId: number, executionId: string) {
  return http.post<{ execution_id: string; cancellation_requested: boolean; status: string; cleanup_confirmed: boolean }>(
    `/agent/conversations/${conversationId}/executions/${encodeURIComponent(executionId)}/cancel`,
  )
}

export async function sendConversationMessage(conversationId: number, message: string, onEvent?: (event: AgentStreamEvent) => void, signal?: AbortSignal) {
  if (onEvent) {
    const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || '/api/v1'}/agent/conversations/${conversationId}/stream`, {
      method: 'POST', headers: { 'Content-Type': 'application/json',
        'Idempotency-Key': crypto.randomUUID(),
        Authorization: `Bearer ${localStorage.getItem('logistics_dispatch_access_token') || ''}` },
      body: JSON.stringify({ message }),
      signal,
    })
    let execution: AgentSendMessageResponse['execution'] = undefined
    let failed = false
    await readAgentStream(response, event => {
      onEvent(event)
      if (event.event_type === 'message_complete') execution = event.payload.execution
      if (['error', 'cancelled'].includes(event.event_type)) failed = true
    })
    if (failed) throw new Error('任务未完成')
    return { data: { execution } }
  }
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
