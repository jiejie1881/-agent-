const TOKEN_KEY = 'driver_access_token'
const USER_KEY = 'driver_user'
const REFRESH_KEY = 'driver_refresh_token'
let sessionVersion = 0
let redirecting = false

function getToken() { return wx.getStorageSync(TOKEN_KEY) || '' }
function setSession(payload) {
  sessionVersion += 1
  redirecting = false
  wx.setStorageSync(TOKEN_KEY, payload.access_token)
  wx.setStorageSync(USER_KEY, payload.user)
  if (payload.refresh_token) wx.setStorageSync(REFRESH_KEY, payload.refresh_token)
  else wx.removeStorageSync(REFRESH_KEY)
}
function clearSession() {
  sessionVersion += 1
  wx.removeStorageSync(TOKEN_KEY)
  wx.removeStorageSync(USER_KEY)
  wx.removeStorageSync(REFRESH_KEY)
  const app = getApp()
  if (app && app.globalData) app.globalData.user = null
}
function redirectToLogin() {
  if (redirecting) return
  redirecting = true
  wx.reLaunch({ url: '/pages/login/index', complete() { redirecting = false } })
}
function ensureLogin() {
  if (getToken()) return true
  redirectToLogin()
  return false
}

module.exports = { getToken, setSession, clearSession, ensureLogin, redirectToLogin, getSessionVersion() { return sessionVersion } }
