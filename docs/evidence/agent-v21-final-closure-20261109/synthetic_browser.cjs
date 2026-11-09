const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require(path.resolve('.local/browser-acceptance/node_modules/playwright-core'));

function events(text) {
  return [...text.matchAll(/^data: (.+)$/gm)].map(match => JSON.parse(match[1]));
}

async function main() {
  const base = new URL(process.env.V21_SYNTHETIC_URL);
  const peer = new URL(process.env.V21_BACKEND_B);
  assert.equal(base.hostname, '127.0.0.1');
  assert.equal(peer.hostname, '127.0.0.1');
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const page = await browser.newPage({baseURL: base.href});
  const screenshot = name => page.screenshot({path: path.join(process.env.V21_EVIDENCE_DIR, name)});
  try {
    await page.goto('/login?redirect=/agent');
    await page.locator('input[autocomplete="username"]').fill('v21-closure-a');
    await page.locator('input[type="password"]').fill(process.env.V21_PROBE_PASSWORD);
    await page.getByRole('button', {name: '登录', exact: true}).click();
    await page.waitForURL(url => url.pathname === '/agent');
    await page.getByText('合成模型，仅用于隔离验收').waitFor();
    const [created] = await Promise.all([
      page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/agent/conversations')),
      page.getByRole('button', {name: '新建会话'}).click(),
    ]);
    const {id} = await created.json();
    const api = `/api/v1/agent/conversations/${id}`;

    async function send(message) {
      await page.getByPlaceholder(/输入调度查询/).fill(message);
      const [response] = await Promise.all([
        page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(`${api}/stream`)),
        page.getByRole('button', {name: '发送', exact: true}).click(),
      ]);
      assert.equal(response.status(), 200);
      return response;
    }

    const completed = await send('查看车辆');
    await page.getByText('合成模型验收：', {exact: true}).waitFor();
    await screenshot('synthetic-first-token.png');
    const completedEvents = events(await completed.text());
    assert.equal(completedEvents.at(-1).event_type, 'message_complete');
    assert.ok(completedEvents.filter(e => e.event_type === 'token').length >= 2);
    assert.ok(completedEvents.some(e => e.event_type === 'tool_call_result' && e.payload.status === 'SUCCEEDED'));
    await page.getByText(/此回复仅用于验证流式传输/).first().waitFor();
    await page.getByRole('button', {name: '发送', exact: true}).waitFor();

    const cancelled = await send('查看车辆并测试停止生成');
    await page.getByText('合成模型验收：', {exact: true}).waitFor();
    const token = await page.evaluate(() => localStorage.getItem('logistics_dispatch_access_token'));
    const headers = {Authorization: `Bearer ${token}`};
    const other = await page.request.post(new URL(`${api}/stream/cancel`, peer).href, {headers});
    assert.equal(other.status(), 200);
    assert.equal((await other.json()).requested, false);
    await page.getByRole('button', {name: '停止生成', exact: true}).click();
    const cancelledEvents = events(await cancelled.text());
    assert.equal(cancelledEvents.at(-1).event_type, 'cancelled');
    const reports = await (await page.request.get(new URL(`${api}/executions`, peer).href, {headers})).json();
    assert.ok(reports.some(report => report.status === 'CANCELLED'));
    await screenshot('synthetic-cancelled.png');
    console.log(JSON.stringify({status: 'PASS', model: 'synthetic_fixture', conversation_id: id,
      tool_result: 'SUCCEEDED', stream_event_types: completedEvents.map(event => event.event_type),
      complete_trace_id: completedEvents[0].trace_id, cancel_trace_id: cancelledEvents[0].trace_id,
      same_instance_cancel: 'CANCELLED', cross_instance_cancel: 'FAIL_LOCAL_REGISTRY'}));
  } catch (error) {
    await screenshot('synthetic-failure.png');
    throw error;
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
