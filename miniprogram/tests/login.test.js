const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

function loadModule(relativePath, dependencies, globals = {}) {
  const filename = path.join(__dirname, '..', relativePath)
  const context = {
    module: { exports: {} },
    require(name) { return dependencies[name] },
    ...globals
  }
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), context, { filename })
  return context.module.exports
}

function loginPage(login) {
  const calls = { toasts: [], tabs: [], sessions: [] }
  const app = { globalData: {} }
  let pageDefinition
  loadModule('pages/login/index.js', {
    '../../services/auth': { login },
    '../../utils/auth': {
      getToken() { return null },
      setSession(value) { calls.sessions.push(value) }
    }
  }, {
    Page(value) { pageDefinition = value },
    getApp() { return app },
    wx: {
      showToast(value) { calls.toasts.push(value) },
      switchTab(value) { calls.tabs.push(value) }
    }
  })
  const page = {
    ...pageDefinition,
    data: { ...pageDefinition.data, username: 'demo_driver_v1', password: 'entered-password' },
    setData(value) { Object.assign(this.data, value) }
  }
  return { page, calls, app }
}

test('login 401 stays on the page and retains input', async () => {
  const { page, calls } = loginPage(async () => {
    const error = new Error('用户名或密码错误')
    error.statusCode = 401
    throw error
  })
  await page.submit()
  assert.match(page.data.error, /用户名或密码错误/)
  assert.equal(page.data.username, 'demo_driver_v1')
  assert.equal(page.data.loading, false)
  assert.equal(calls.toasts.length, 1)
  assert.equal(calls.tabs.length, 0)
  assert.equal(calls.sessions.length, 0)
})

test('successful login saves session and opens home', async () => {
  const result = { access_token: 'test-token', user: { username: 'demo_driver_v1' } }
  const { page, calls, app } = loginPage(async () => result)
  await page.submit()
  assert.equal(calls.sessions.length, 1)
  assert.equal(calls.tabs[0].url, '/pages/home/index')
  assert.equal(app.globalData.user.username, 'demo_driver_v1')
  assert.equal(page.data.loading, false)
})

test('unbound driver and network failure keep page visible with feedback', async () => {
  for (const [statusCode, sourceMessage, expected] of [
    [409, '当前司机未绑定车辆，请联系管理员', /未绑定车辆/],
    [0, '网络连接失败，请稍后重试', /网络连接失败/],
    [500, 'Internal Server Error', /登录失败，请稍后重试/]
  ]) {
    const { page, calls } = loginPage(async () => {
      const error = new Error(sourceMessage)
      error.statusCode = statusCode
      throw error
    })
    await page.submit()
    assert.match(page.data.error, expected)
    assert.equal(calls.toasts.length, 1)
    assert.equal(calls.tabs.length, 0)
    assert.equal(page.data.loading, false)
  }
})

test('login rejects repeated submit while loading', async () => {
  let resolveLogin
  let count = 0
  const { page } = loginPage(() => {
    count += 1
    return new Promise((resolve) => { resolveLogin = resolve })
  })
  const first = page.submit()
  await page.submit()
  assert.equal(count, 1)
  resolveLogin({ user: { username: 'demo_driver_v1' } })
  await first
  assert.equal(page.data.loading, false)
})

test('request login 401 rejects without relaunch; other 401 still relaunches', async () => {
  const calls = { relaunches: [], headers: [] }
  const request = loadModule('utils/request.js', {
    './config': { API_BASE_URL: 'http://127.0.0.1:8000/api/driver' },
    './auth': { getToken() { return 'test-token' }, getSessionVersion() { return 0 }, clearSession() { calls.cleared = true }, redirectToLogin() { calls.relaunches.push({ url: '/pages/login/index' }) } }
  }, {
    wx: {
      request(options) {
        calls.headers.push(options.header)
        options.success({ statusCode: 401, data: { detail: '用户名或密码错误' } })
      },
      reLaunch(value) { calls.relaunches.push(value) }
    }
  })
  await assert.rejects(request({ url: '/auth/login', method: 'POST' }), /用户名或密码错误/)
  assert.equal(calls.relaunches.length, 0)
  assert.equal(calls.headers[0].Authorization, 'Bearer test-token')
  await assert.rejects(request({ url: '/tasks/today' }), /用户名或密码错误/)
  assert.equal(calls.relaunches.length, 1)
  assert.equal(calls.cleared, true)
})

test('network and server errors show safe messages', async () => {
  for (const [response, expected] of [
    [{ statusCode: 500, data: 'Internal Server Error' }, /服务器暂时不可用/],
    [null, /网络连接失败/]
  ]) {
    const request = loadModule('utils/request.js', {
      './config': { API_BASE_URL: 'http://127.0.0.1:8000/api/driver' },
      './auth': { getToken() { return null }, getSessionVersion() { return 0 }, clearSession() {} }
    }, {
      wx: { request(options) { assert.equal(options.timeout, 30000); response ? options.success(response) : options.fail({ errMsg: 'wx.request:fail' }) } }
    })
    await assert.rejects(request({ url: '/auth/login' }), expected)
  }
})
