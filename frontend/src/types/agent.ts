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
}

export interface AgentSendMessageResponse {
  conversation_id: number
  message: AgentConversationMessage
  tool_calls_count: number
  used_tools: string[]
  request_id: string
}

export interface AgentStatelessChatResponse {
  content: string
  tool_calls_count: number
  used_tools: string[]
  request_id: string
}
