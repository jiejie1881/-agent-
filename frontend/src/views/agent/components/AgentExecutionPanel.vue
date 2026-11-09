<script setup lang="ts">
import type { AgentExecutionReport } from '@/types/agent'

defineProps<{
  executions: AgentExecutionReport[]
  resumeLoadingId?: string | null
  disabled?: boolean
  statusError?: boolean
  cancelPending?: boolean
}>()
const emit = defineEmits<{ resume: [execution: AgentExecutionReport]; cancel: [execution: AgentExecutionReport] }>()

const states: Record<string, string> = {
  RUNNING: '执行中', COMPLETED: '已完成', WAITING_APPROVAL: '等待人工确认',
  FAILED: '执行失败', LIMIT_REACHED: '已达步骤上限', CANCELLED: '已取消',
  CLARIFICATION: '需要补充信息', SUCCEEDED: '成功', CACHED: '已核验并复用', SKIPPED: '条件不满足，未执行',
  RECOVERING: '恢复执行中', RETRYING: '等待有限重试', TIMED_OUT: '执行超时', MANUAL_REVIEW: '需要人工处理',
  COMPLETION_UNKNOWN: '提交结果待核实，勿重复操作',
}
const nodes: Record<string, string> = {
  intent: '识别任务', planner: '制定计划', validate_plan: '检查计划', tools: '执行工具',
  analyze: '分析结果', decide: '决定下一步', replan: '重新规划', finish: '汇总结果',
  approval: '人工审批', execute: '确认操作', failure: '任务停止',
  recovery: '恢复检查', retry: '重试检查',
}
</script>

<template>
  <aside v-if="executions.length || statusError" class="execution-panel" aria-label="任务执行过程">
    <p v-if="statusError" class="execution-error" role="status">执行状态暂时更新失败，当前保留上次记录。请刷新核对，勿重复提交操作。</p>
    <details v-for="execution in executions" :key="execution.execution_id" :open="executions[0] === execution">
      <summary>
        {{ states[execution.status] ?? execution.status }} · {{ nodes[execution.current_node] ?? execution.current_node }}
        · {{ execution.tool_attempts }} 次工具调用
      </summary>
      <p class="execution-meta">执行编号 {{ execution.execution_id }} · 重规划 {{ execution.replans }} 次 · {{ Math.round(execution.elapsed_ms) }} ms</p>
      <p v-if="execution.status === 'WAITING_APPROVAL'" role="status">业务操作尚未执行，请核对会话中的人工确认卡片。</p>
      <p v-if="execution.write_outcome" role="status">事务结果：{{ execution.write_outcome === 'COMMITTED' ? '已提交，取消不能撤销' : execution.write_outcome === 'CANCELLED_BEFORE_COMMIT' ? '提交前取消，业务写入已回滚' : '提交结果待核实，禁止自动重试' }}</p>
      <p v-if="cancelPending" role="status">正在请求取消，等待执行器回收；请以服务端最终状态为准。</p>
      <details v-if="execution.capabilities?.length">
        <summary>工具取消能力</summary>
        <p v-for="item in execution.capabilities" :key="item.tool">{{ item.tool }} · {{ item.capability }} · {{ item.hard_termination ? '独立进程可终止' : '不承诺硬终止' }} · {{ item.scope }}</p>
      </details>
      <p v-if="execution.recovery_reason" class="execution-meta">恢复检查：{{ execution.recovery_reason }}</p>
      <button v-if="['RUNNING', 'RECOVERING', 'RETRYING'].includes(execution.status) && execution.can_resume !== true"
        type="button" class="resume-button" :disabled="cancelPending" @click="emit('cancel', execution)">请求取消执行</button>
      <button v-if="execution.can_resume === true" type="button" class="resume-button"
        :disabled="disabled || resumeLoadingId != null"
        @click="emit('resume', execution)">
        {{ resumeLoadingId === execution.execution_id ? '正在恢复…' : '恢复执行' }}
      </button>
      <ol v-if="execution.plan.length">
        <li v-for="step in execution.plan" :key="step.id">
          {{ step.id }} · {{ step.tool }}
          <span v-if="step.depends_on.length">（依赖 {{ step.depends_on.join('、') }}）</span>
          <strong v-if="step.requires_confirmation"> · 需人工确认</strong>
        </li>
      </ol>
      <ul class="execution-events">
        <li v-for="(event, index) in execution.events" :key="index">
          {{ nodes[event.node] ?? event.node }}
          <span v-if="event.step_id"> · {{ event.step_id }} / {{ event.tool }}</span>
          — {{ states[event.status] ?? event.status }}
          <span v-if="event.parallel_group">（并行组 {{ event.parallel_group }}）</span>
          <span v-if="event.elapsed_ms"> · {{ Math.round(event.elapsed_ms) }} ms</span>
          <span v-if="event.error_code" class="execution-error"> · {{ event.error_code }}</span>
          <span v-if="event.error_category" class="execution-error"> · {{ event.error_category }}</span>
          <span v-if="(event.max_attempts ?? 1) > 1"> · 第 {{ event.attempt ?? 1 }}/{{ event.max_attempts }} 次尝试</span>
          <span v-if="(event.retry_delay_ms ?? 0) > 0"> · 等待 {{ event.retry_delay_ms }} ms</span>
          <span v-if="event.result_summary && Object.keys(event.result_summary).length"> · 结果 {{ JSON.stringify(event.result_summary) }}</span>
        </li>
      </ul>
      <section v-if="execution.final_message" class="execution-result" aria-label="执行结果">
        <strong>执行结果</strong>
        <p>{{ execution.final_message }}</p>
      </section>
    </details>
  </aside>
</template>

<style scoped>
.execution-panel { max-height: 280px; overflow: auto; border-top: 1px solid #e4eaf2; padding: 10px 18px; background: #f6f9fd; font-size: 13px; }
summary { cursor: pointer; font-weight: 600; }
.execution-meta { color: #64748b; overflow-wrap: anywhere; }
.execution-events { padding-left: 20px; line-height: 1.8; }
.execution-error { color: #b91c1c; }
.resume-button { padding: 5px 12px; color: #1d4ed8; background: #fff; border: 1px solid #93b8e9; border-radius: 6px; cursor: pointer; }
.resume-button:disabled { opacity: 0.55; cursor: default; }
.execution-result p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
</style>
