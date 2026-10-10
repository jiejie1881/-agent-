const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const test = require('node:test')

function load(file, dependencies, globals) {
  const context = { module: { exports: {} }, require: (name) => dependencies[name], ...globals }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), context)
  return context.module.exports
}
function setup(getProfile = async () => ({ username: 'actual_driver', vehicle: null })) {
  const storage = new Map([['unrelated', 'keep']])
  const calls = { redirects: [], requests: [], uploads: [], tabs: [], navigation: [] }
  const app = { globalData: { user: null } }
  const wx = {
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: (key) => storage.delete(key),
    reLaunch: (options) => calls.redirects.push(options),
    request: (options) => calls.requests.push(options),
    uploadFile: (options) => calls.uploads.push(options),
    showModal: (options) => { calls.modal = options },
    switchTab: (options) => calls.tabs.push(options),
    navigateTo: (options) => calls.navigation.push(options),
    getAccountInfoSync: () => ({ miniProgram: { version: '' } })
  }
  const globals = { wx, getApp: () => app }
  const auth = load('utils/auth.js', {}, globals)
  auth.setSession({ access_token: 'first', refresh_token: 'refresh', user: { username: 'actual_driver' } })
  app.globalData.user = { username: 'actual_driver' }
  let definition
  load('pages/profile/index.js', { '../../services/auth': { getProfile }, '../../utils/auth': auth }, { ...globals, Page(value) { definition = value } })
  const page = { ...definition, data: { ...definition.data }, setData(value) { Object.assign(this.data, value) } }
  const request = load('utils/request.js', { './auth': auth, './config': { API_BASE_URL: 'http://example.invalid' } }, globals)
  const task = load('services/task.js', { '../utils/auth': auth, '../utils/request': request, '../utils/config': { API_BASE_URL: 'http://example.invalid' } }, globals)
  return { auth, page, request, task, calls, storage, app, wx }
}
test('profile renders real fields and handles unbound vehicle', async () => {
  for (const vehicle of [null, { plate_number: 'real-plate', code: 'real-code', vehicle_type_name: 'real-type' }]) {
    const { page } = setup(async () => ({ username: 'actual_driver', vehicle }))
    await page.load()
    assert.equal(page.data.profile.username, 'actual_driver')
    assert.equal(page.data.profile.vehicle, vehicle)
    assert.equal(page.data.loading, false)
    assert.equal(page.data.error, '')
  }
})
test('profile failure ends loading and retry succeeds; null response stays empty', async () => {
  let fail = true
  const { page } = setup(async () => { if (fail) throw new Error('网络连接失败'); return null })
  await page.load()
  assert.equal(page.data.error, '网络连接失败')
  assert.equal(page.data.loading, false)
  fail = false
  await page.load()
  assert.equal(page.data.error, '')
  assert.equal(page.data.profile, null)
})
test('cancel logout preserves auth; confirm clears only auth and memory', () => {
  const { page, auth, calls, storage, app } = setup()
  page.logout()
  calls.modal.success({ confirm: false }); calls.modal.complete()
  assert.equal(auth.getToken(), 'first')
  assert.equal(calls.redirects.length, 0)
  page.logout()
  calls.modal.success({ confirm: true }); calls.modal.complete()
  assert.equal(auth.getToken(), '')
  assert.equal(storage.has('driver_refresh_token'), false)
  assert.equal(storage.has('driver_user'), false)
  assert.equal(storage.get('unrelated'), 'keep')
  assert.equal(app.globalData.user, null)
  assert.equal(calls.redirects[0].url, '/pages/login/index')
})
test('logout blocks protected request and upload, coalesces login redirects', async () => {
  const { auth, request, task, calls } = setup()
  auth.clearSession()
  await assert.rejects(request({ url: '/profile' }), /请先登录/)
  await assert.rejects(task.uploadProof(1, 1, 'image'), /请先登录/)
  assert.equal(calls.requests.length, 0)
  assert.equal(calls.uploads.length, 0)
  assert.equal(calls.redirects.length, 1)
})
test('late profile cannot repopulate after logout', async () => {
  let resolve
  const { page, calls } = setup(() => new Promise((r) => { resolve = r }))
  const pending = page.load()
  page.logout(); calls.modal.success({ confirm: true }); calls.modal.complete()
  resolve({ username: 'old_driver' })
  await pending
  assert.equal(page.data.profile, null)
  assert.equal(page.data.loggedIn, false)
  assert.equal(page.data.loading, false)
})
test('old 401 cannot erase new login; new session can request', async () => {
  const { request, auth, calls } = setup()
  const old = request({ url: '/profile' })
  auth.clearSession()
  auth.setSession({ access_token: 'new', user: { username: 'new_driver' } })
  calls.requests[0].success({ statusCode: 401, data: {} })
  await assert.rejects(old, /登录状态已变化/)
  assert.equal(auth.getToken(), 'new')
  const current = request({ url: '/profile' })
  assert.equal(calls.requests[1].header.Authorization, 'Bearer new')
  calls.requests[1].success({ statusCode: 200, data: { username: 'new_driver' } })
  assert.equal((await current).username, 'new_driver')
})
test('401 clears refresh, user cache and global user', async () => {
  const { request, calls, storage, app } = setup()
  const pending = request({ url: '/profile' })
  calls.requests[0].success({ statusCode: 401, data: { detail: '登录过期' } })
  await assert.rejects(pending, /登录过期/)
  assert.equal(storage.has('driver_access_token'), false)
  assert.equal(storage.has('driver_refresh_token'), false)
  assert.equal(app.globalData.user, null)
  assert.equal(calls.redirects.length, 1)
})
test('history uses tab navigation and about reads actual release version', () => {
  const { page, calls } = setup()
  page.openHistory()
  assert.equal(calls.tabs[0].url, '/pages/history/index')
  page.showAbout()
  assert.match(calls.modal.content, /开发版（未发布）/)
})
test('profile view uses native tags and keeps actions outside data conditions', () => {
  const markup = fs.readFileSync(path.join(__dirname, '../pages/profile/index.wxml'), 'utf8')
  assert.doesNotMatch(markup, /<strong/)
  for (const text of ['暂未绑定车辆', '重新加载资料', '正在加载', '配送历史', '关于系统', '退出登录']) assert.ok(markup.includes(text))
})
test('proof upload keeps JWT and rejects response from an ended session', async () => {
  const { auth, task, calls } = setup()
  const pending = task.uploadProof(2, 3, 'image.jpg')
  assert.equal(calls.uploads[0].header.Authorization, 'Bearer first')
  assert.match(calls.uploads[0].url, /tasks\/2\/stops\/3\/proofs$/)
  auth.clearSession()
  calls.uploads[0].success({ statusCode: 200, data: '{"url":"/uploads/proof.jpg"}' })
  await assert.rejects(pending, /登录状态已变化/)
})
test('leaving profile prevents late data writes; re-entering reloads', async () => {
  let resolve
  const { page } = setup(() => new Promise((r) => { resolve = r }))
  const pending = page.load()
  page.onHide()
  resolve({ username: 'old' })
  await pending
  assert.equal(page.data.profile, null)
  const next = page.load()
  resolve({ username: 'current', vehicle: null })
  await next
  assert.equal(page.data.profile.username, 'current')
  assert.equal(page.data.loading, false)
})
test('native logout modal failure offers visible confirmation without signing out', () => {
  const { page, calls, auth } = setup()
  page.logout()
  calls.modal.fail({ errMsg: 'showModal:fail' }); calls.modal.complete()
  assert.equal(page.data.confirming, false)
  assert.equal(page.data.logoutFallback, true)
  assert.equal(auth.getToken(), 'first')
  page.cancelLogout()
  assert.equal(page.data.logoutFallback, false)
  assert.equal(auth.getToken(), 'first')
  page.logout(); calls.modal.fail({})
  page.confirmLogout()
  assert.equal(auth.getToken(), '')
  assert.equal(calls.redirects.length, 1)
})
test('synchronous modal failure releases button and offers fallback', () => {
  const { page, wx, auth } = setup()
  wx.showModal = () => { throw new Error('native modal unavailable') }
  page.logout()
  assert.equal(page.data.confirming, false)
  assert.equal(page.data.logoutFallback, true)
  assert.equal(auth.getToken(), 'first')
})
test('re-entering profile clears stale disabled logout state', () => {
  const { page } = setup()
  page.data.confirming = true
  page.onShow()
  assert.equal(page.data.confirming, false)
})

test('leave entry navigates to registered page and ignores repeated taps', () => {
  const { page, calls } = setup()
  page.openLeave(); page.openLeave()
  assert.equal(calls.navigation.length, 1)
  assert.equal(calls.navigation[0].url, '/pages/leave/index')
  const app = JSON.parse(fs.readFileSync(path.join(__dirname, '../app.json'), 'utf8'))
  assert.ok(app.pages.includes('pages/leave/index'))
  calls.navigation[0].complete()
  assert.equal(page.data.openingLeave, false)
})

test('leave navigation failure displays actual reason and permits retry', () => {
  const { page, calls } = setup()
  page.openLeave()
  calls.navigation[0].fail({ errMsg: 'navigateTo:fail page not found' })
  calls.navigation[0].complete()
  assert.match(page.data.leaveNavigationError, /page not found/)
  assert.equal(page.data.openingLeave, false)
  page.openLeave()
  assert.equal(calls.navigation.length, 2)
  assert.equal(page.data.leaveNavigationError, '')
})

test('leave entry catches native errors and does not navigate after logout', () => {
  const { page, wx, auth, calls } = setup()
  wx.navigateTo = () => { throw Error('navigation unavailable') }
  page.openLeave()
  assert.equal(page.data.openingLeave, false)
  assert.match(page.data.leaveNavigationError, /navigation unavailable/)
  auth.clearSession()
  page.openLeave()
  assert.equal(calls.navigation.length, 0)
  assert.equal(calls.redirects.length, 1)
})
