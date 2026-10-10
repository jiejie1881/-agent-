const service = require('../../services/task')
const auth = require('../../utils/auth')
Page({
  data: { tasks: [], loading: false, error: '' },
  onShow() { if (auth.ensureLogin()) this.load() },
  onPullDownRefresh() { this.load().finally(() => wx.stopPullDownRefresh()) },
  async load() { this.setData({ loading: true, error: '' }); try { this.setData({ tasks: await service.getTodayTasks() }) } catch (error) { this.setData({ error: error.message }) } finally { this.setData({ loading: false }) } },
  openTask(event) { wx.navigateTo({ url: '/pages/task-detail/index?id=' + event.currentTarget.dataset.id }) }
})
