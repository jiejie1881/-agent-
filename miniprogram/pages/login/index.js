const authService = require('../../services/auth')
const auth = require('../../utils/auth')

Page({
  data: { username: '', password: '', loading: false, error: '' },
  onLoad() {
    if (auth.getToken()) wx.switchTab({ url: '/pages/home/index' })
  },
  onUsername(event) { this.setData({ username: event.detail.value }) },
  onPassword(event) { this.setData({ password: event.detail.value }) },
  async submit() {
    if (this.data.loading) return
    if (!this.data.username.trim() || !this.data.password) {
      this.setData({ error: '请输入司机账号和密码' })
      wx.showToast({ title: '请输入司机账号和密码', icon: 'none' })
      return
    }
    this.setData({ loading: true, error: '' })
    try {
      const result = await authService.login(this.data.username.trim(), this.data.password)
      auth.setSession(result)
      getApp().globalData.user = result.user
      wx.switchTab({ url: '/pages/home/index' })
    } catch (error) {
      const message = error.statusCode === 401
        ? '用户名或密码错误；如账号被停用，请联系管理员'
        : error.statusCode >= 500
          ? '登录失败，请稍后重试'
          : error.message || '登录失败，请稍后重试'
      this.setData({ error: message })
      wx.showToast({
        title: error.statusCode === 401 ? '用户名或密码错误' : message,
        icon: 'none',
        duration: 3000
      })
    } finally {
      this.setData({ loading: false })
    }
  }
})
