// Headless Edge against the published port of the isolated frontend.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('../../.local/browser-acceptance/node_modules/playwright-core');

async function main() {
  const base = new URL(process.env.V21_FRONTEND_URL);
  assert.equal(base.hostname, '127.0.0.1');
  const evidence = path.resolve(process.env.V21_EVIDENCE_DIR);
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const requests = [];
  const screenshot = (page, name) => page.screenshot({path: path.join(evidence, name)});

  async function login(user) {
    const context = await browser.newContext({baseURL: base.href});
    const page = await context.newPage();
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.origin === base.origin && url.pathname.startsWith('/api/')) {
        requests.push({method: response.request().method(), path: url.pathname, status: response.status()});
      }
    });
    await page.goto('/login?redirect=/agent');
    await page.locator('input[autocomplete="username"]').fill(user);
    await page.locator('input[type="password"]').fill(process.env.V21_PROBE_PASSWORD);
    await page.getByRole('button', {name: '登录', exact: true}).click();
    await page.waitForURL(url => url.pathname === '/agent');
    return page;
  }

  try {
    const a = await login('v21-closure-a');
    const [created] = await Promise.all([
      a.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/agent/conversations')),
      a.getByRole('button', {name: '新建会话'}).click(),
    ]);
    assert.equal(created.status(), 201);
    const {id} = await created.json();
    await a.getByPlaceholder(/输入调度查询/).fill('查询今天尚未完成的合成配送任务');
    const [stream] = await Promise.all([
      a.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(`/${id}/stream`)),
      a.getByRole('button', {name: '发送', exact: true}).click(),
    ]);
    assert.equal(stream.status(), 200);
    assert.match(stream.headers()['content-type'], /text\/event-stream/);
    const trace = stream.headers()['x-agent-trace-id'];
    assert.match(trace, /^[a-f0-9]{32}$/);
    const body = await stream.text();
    const kinds = [...body.matchAll(/^event: (.+)$/gm)].map(match => match[1]);
    assert.ok(kinds.includes('message_start'));
    assert.ok(kinds.includes('error') || kinds.includes('agent_status'));
    await screenshot(a, 'browser-stream.png');
    const [loaded] = await Promise.all([
      a.waitForResponse(r => r.request().method() === 'GET' && /\/agent\/conversations\?/.test(r.url())),
      a.reload(),
    ]);
    assert.ok((await loaded.json()).some(item => item.id === id));
    await screenshot(a, 'browser-refresh.png');

    const b = await login('v21-closure-b');
    const [foreignList] = await Promise.all([
      b.waitForResponse(r => r.request().method() === 'GET' && /\/agent\/conversations\?/.test(r.url())),
      b.reload(),
    ]);
    assert.ok(!(await foreignList.json()).some(item => item.id === id));
    await screenshot(b, 'browser-other-user.png');
    console.log(JSON.stringify({status: 'PASS', scope: 'browser_login_create_error_stream_refresh_isolation',
      conversation_id: id, trace_id: trace, event_types: kinds, model: 'NOT RUN', requests}));
  } catch (error) {
    const pages = browser.contexts().flatMap(context => context.pages());
    if (pages.length) await screenshot(pages.at(-1), 'browser-failure.png');
    throw error;
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
