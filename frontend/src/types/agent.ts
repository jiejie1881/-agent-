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
  execution?: AgentExecutionReport | null
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
  execution?: AgentExecutionReport | null
}

export interface AgentExecutionEvent {
  node: string
  step_id?: string | null
  tool?: string | null
  status: string
  elapsed_ms: number
  error_code?: string | null
  input_fields: string[]
  output_fields: string[]
  parallel_group?: string | null
  result_summary?: Record<string, string | number | boolean | null>
  attempt?: number
  max_attempts?: number
  retry_delay_ms?: number
  error_category?: string | null
}

export interface AgentExecutionReport {
  execution_id: string
  conversation_id?: number | null
  intent: string
  status: string
  current_node: string
  plan: { id: string; tool: string; depends_on: string[]; input_fields: string[]; output_key: string; requires_confirmation: boolean }[]
  events: AgentExecutionEvent[]
  completed_steps: number
  tool_attempts: number
  replans: number
  elapsed_ms: number
  revision?: number
  can_resume?: boolean
  recovery_reason?: string | null
  final_message?: string | null
  write_outcome?: 'CANCELLED_BEFORE_COMMIT' | 'COMMITTED' | 'COMPLETION_UNKNOWN' | null
  capabilities?: { tool: string; capability: string; hard_termination: boolean; scope: string }[]
}
