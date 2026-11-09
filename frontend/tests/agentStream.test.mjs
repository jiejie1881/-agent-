import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
const source = fs.readFileSync(new URL('../src/utils/agentStream.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
const { readAgentStream } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
function frame(sequence, event_type, payload = {}) {
  return `id: ${sequence}\ndata: ${JSON.stringify({ sequence, trace_id: 'test', event_type, payload })}\n\n`
}
test('SSE handles split UTF8, heartbeats and duplicate sequences', async () => {
  const bytes = new TextEncoder().encode(': heartbeat\n\n' + frame(1, 'token', { text: '车辆' }) + frame(1, 'token') + frame(2, 'message_complete'))
  const seen = []
  const response = new Response(new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i++) controller.enqueue(bytes.slice(i, i + 1))
    controller.close()
  } }))
  await readAgentStream(response, event => seen.push(event))
  assert.equal(seen.length, 2)
  assert.equal(seen[0].payload.text, '车辆')
})
test('SSE rejects missing sequence and abnormal termination', async () => {
  await assert.rejects(readAgentStream(new Response(frame(2, 'message_complete')), () => {}), /事件缺失/)
  await assert.rejects(readAgentStream(new Response(frame(1, 'token')), () => {}), /异常中断/)
})
