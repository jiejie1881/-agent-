const authService = require('../../services/auth')
const taskService = require('../../services/task')
const auth = require('../../utils/auth')

Page({
  data: { profile: null, tasks: [], today: '', loading: false, error: '' },
  onLoad() {
    const now = new Date()
    const today = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0')
    this.setData({ today: today })
  },
  onShow() { if (auth.ensureLogin()) this.load() },
  onPullDownRefresh() { this.load().finally(() => wx.stopPullDownRefresh()) },
  async load() {
    this.setData({ loading: true, error: '' })
    try {
      const result = await Promise.all([authService.getProfile(), taskService.getTodayTasks()])
      if (result[0]) result[0].today_schedules = result[0].today_schedules || []
      this.setData({ profile: result[0], tasks: result[1] })
    } catch (error) { this.setData({ error: error.message }) }
    finally { this.setData({ loading: false }) }
  },
  openTask(event) { wx.navigateTo({ url: '/pages/task-detail/index?id=' + event.currentTarget.dataset.id }) }
})
