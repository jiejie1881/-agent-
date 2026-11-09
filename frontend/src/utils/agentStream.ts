export type AgentStreamEvent = {
  conversation_id: number; message_id: string; trace_id: string; sequence: number
  event_type: string; timestamp: string; payload: Record<string, any>
}

export async function readAgentStream(response: Response, onEvent: (event: AgentStreamEvent) => void) {
  if (!response.ok || !response.body) throw new Error('流式请求失败')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = '', last = 0, terminal = false, trace = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
        const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
        if (!data) continue
        const event = JSON.parse(data) as AgentStreamEvent
        if (trace && trace !== event.trace_id) throw new Error('流式请求标识不匹配')
        trace = event.trace_id
        if (event.sequence <= last) continue
        if (event.sequence !== last + 1) throw new Error('流式事件缺失，请刷新执行状态')
        last = event.sequence
        onEvent(event)
        terminal ||= ['message_complete', 'cancelled', 'error'].includes(event.event_type)
      }
      if (done) break
    }
    if (!terminal) throw new Error('连接异常中断，请刷新执行状态；不要自动重发任务')
  } finally { await reader.cancel(); reader.releaseLock() }
}
