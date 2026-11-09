const { API_BASE_URL } = require('./config')
const auth = require('./auth')

function request(options) {
  const token = auth.getToken()
  const isLogin = options.url === '/auth/login'
  if (!isLogin && !token) {
    auth.ensureLogin()
    return Promise.reject(new Error('请先登录司机账号'))
  }
  const version = auth.getSessionVersion()
  return new Promise((resolve, reject) => {
    wx.request({
      url: API_BASE_URL + options.url,
      method: options.method || 'GET',
      timeout: 30000,
      data: options.data || {},
      header: Object.assign(
        { 'content-type': 'application/json' },
        options.header || {},
        token ? { Authorization: 'Bearer ' + token } : {}
      ),
      success(response) {
        // 退出或切换账号后，旧请求不能回写资料或清除新会话。
        if (!isLogin && version !== auth.getSessionVersion()) {
          reject(new Error('登录状态已变化，请重新加载'))
          return
        }
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response.data)
          return
        }
        if (response.statusCode === 401 && !isLogin) {
          auth.clearSession()
          auth.redirectToLogin()
        }
        const body = response.data || {}
        const message = response.statusCode >= 500
          ? '服务器暂时不可用，请稍后重试'
          : (typeof body.detail === 'string' && body.detail) || '请求失败，请稍后重试'
        const error = new Error(message)
        error.statusCode = response.statusCode
        error.businessCode = body.code || null
        reject(error)
      },
      fail() {
        const networkError = new Error('网络连接失败，请稍后重试')
        networkError.statusCode = 0
        reject(networkError)
      }
    })
  })
}

module.exports = request
