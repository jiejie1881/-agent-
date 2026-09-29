import type { TimestampFields } from '@/types/common'

export type AgentMessageRole = 'USER' | 'ASSISTANT'

export interface AgentConversation extends TimestampFields {
  id: number
  title: string
}

export interface AgentConversationMessage {
  id: number
  role: AgentMessageRole
  content: string
  created_at: string
}

export interface AgentConversationDetail extends AgentConversation {
  messages: AgentConversationMessage[]
  pending_actions: AgentPendingAction[]
}

export type AgentPendingActionStatus =
  | 'PENDING'
  | 'CONFIRMED'
  | 'EXECUTED'
  | 'CANCELLED'
  | 'EXPIRED'
  | 'FAILED'

export interface AgentPendingAction {
  id: number
  tool_name: string
  summary: string
  display_data: Record<string, unknown>
  risk_level: string
  risk_message: string
  status: AgentPendingActionStatus
  created_at: string
  expires_at: string
  confirmed_at?: string | null
  executed_at?: string | null
}

export interface AgentSendMessageResponse {
  conversation_id: number
  message: AgentConversationMessage
  tool_calls_count: number
  used_tools: string[]
  request_id: string
  pending_actions: AgentPendingAction[]
}

export interface AgentPendingActionExecutionResponse {
  action: AgentPendingAction
  result: Record<string, unknown>
}

export interface AgentStatelessChatResponse {
  content: string
  tool_calls_count: number
  used_tools: string[]
  request_id: string
}
