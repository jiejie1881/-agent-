const service = require('../../services/auth')
const auth = require('../../utils/auth')
Page({
  data: { profile: null, loading: false, error: '', loggedIn: false, confirming: false, logoutFallback: false, logoutError: '', openingLeave: false, leaveNavigationError: '' },
  onShow() {
    this.setData({ loggedIn: !!auth.getToken(), confirming: false, logoutFallback: false, logoutError: '', openingLeave: false, leaveNavigationError: '' })
    if (auth.ensureLogin()) this.load()
  },
  onHide() { this.requestId = (this.requestId || 0) + 1 },
  onUnload() { this.onHide() },
  onPullDownRefresh() { this.load().finally(() => wx.stopPullDownRefresh()) },
  async load() {
    if (!auth.ensureLogin()) return
    const version = auth.getSessionVersion()
    const requestId = this.requestId = (this.requestId || 0) + 1
    this.setData({ loading: true, error: '', profile: null, loggedIn: true })
    const current = () => requestId === this.requestId && version === auth.getSessionVersion() && !!auth.getToken()
    try {
      const profile = await service.getProfile()
      if (profile) profile.today_schedules = profile.today_schedules || []
      if (current()) this.setData({ profile: profile || null })
    } catch (error) {
      if (current()) this.setData({ error: error.message || '资料加载失败，请重试' })
    } finally {
      if (current()) this.setData({ loading: false })
    }
  },
  openHistory() { if (auth.ensureLogin()) wx.switchTab({ url: '/pages/history/index' }) },
  openLeave() {
    if (this.data.openingLeave || !auth.ensureLogin()) return
    this.setData({ openingLeave: true, leaveNavigationError: '' })
    const failed = (error) => {
      // 保留微信返回的原因，不能把跳转失败表现成无响应。
      const detail = error && error.errMsg ? '（' + error.errMsg + '）' : ''
      this.setData({ openingLeave: false, leaveNavigationError: '请假管理打开失败，请重试；若仍失败，请重新编译小程序。' + detail })
    }
    try {
      wx.navigateTo({
        url: '/pages/leave/index',
        fail: failed,
        complete: () => this.setData({ openingLeave: false })
      })
    } catch (error) {
      failed({ errMsg: error.message })
    }
  },
  showAbout() {
    const info = wx.getAccountInfoSync()
    const version = info.miniProgram.version || '开发版（未发布）'
    wx.showModal({ title: '关于系统', content: '智能物流派车管理系统\n版本：' + version + '\n司机配送端：查看任务、门店签收与配送回单。', showCancel: false })
  },
  logout() {
    if (this.data.confirming || this.data.logoutFallback) return
    this.setData({ confirming: true, logoutError: '' })
    const fallback = () => this.setData({ confirming: false, logoutFallback: true, logoutError: '系统弹窗未能打开，请在下方确认退出。' })
    try {
      wx.showModal({
        title: '退出登录', content: '确认退出当前司机账号吗？',
        success: (result) => { if (result.confirm) this.confirmLogout() },
        fail: fallback,
        complete: () => this.setData({ confirming: false })
      })
    } catch (error) {
      fallback()
    }
  },
  cancelLogout() { this.setData({ logoutFallback: false, logoutError: '', confirming: false }) },
  confirmLogout() {
    this.requestId = (this.requestId || 0) + 1
    auth.clearSession()
    this.setData({ profile: null, loggedIn: false, loading: false, error: '', logoutFallback: false, logoutError: '' })
    auth.redirectToLogin()
  }
})
