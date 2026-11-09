const service = require('../../services/task')
const auth = require('../../utils/auth')

Page({
  data: { taskId: 0, task: null, unprocessedCount: 0, canComplete: false, loading: false, operating: false, error: '' },
  onLoad(options) { this.setData({ taskId: Number(options.id) }) },
  onShow() { if (this.data.taskId && auth.ensureLogin()) this.load(); else this.setData({ task: null, unprocessedCount: 0, canComplete: false }) },
  async load() {
    const version = auth.getSessionVersion()
    this.setData({ loading: true, error: '', task: null, unprocessedCount: 0, canComplete: false })
    try {
      const task = await service.getTask(this.data.taskId)
      task.stops = await Promise.all(task.stops.map(async stop => {
        await service.hydrateProofs(stop)
        stop.proof_urls = stop.proofs.map(proof => proof.full_url).filter(Boolean)
        return stop
      }))
      if (version !== auth.getSessionVersion()) return
      const unprocessedCount = task.stops.filter((item) => item.delivery_status !== 'SIGNED' && item.delivery_status !== 'FAILED').length
      this.setData({ task: task, unprocessedCount: unprocessedCount, canComplete: unprocessedCount === 0 })
    } catch (error) { this.setData({ error: error.message }) }
    finally { this.setData({ loading: false }) }
  },
  openRoute() { wx.navigateTo({ url: '/pages/route/index?id=' + this.data.taskId }) },
  openSign(event) { wx.navigateTo({ url: '/pages/sign/index?taskId=' + this.data.taskId + '&stopId=' + event.currentTarget.dataset.stopId }) },
  resubmitProof(event) { wx.navigateTo({ url: '/pages/sign/index?taskId=' + this.data.taskId + '&stopId=' + event.currentTarget.dataset.stopId + '&replacesProofId=' + event.currentTarget.dataset.proofId }) },
  openFail(event) { wx.navigateTo({ url: '/pages/delivery-fail/index?taskId=' + this.data.taskId + '&stopId=' + event.currentTarget.dataset.stopId }) },
  previewProof(event) { if (auth.ensureLogin() && event.currentTarget.dataset.current) wx.previewImage({ current: event.currentTarget.dataset.current, urls: event.currentTarget.dataset.urls }) },
  async arrive(event) {
    if (this.data.operating) return
    const stopId = event.currentTarget.dataset.stopId
    const confirmed = await new Promise((resolve) => wx.showModal({ title: '确认到店', content: '确认已经到达该门店吗？', success: (result) => resolve(result.confirm) }))
    if (!confirmed) return
    this.setData({ operating: true, error: '' })
    try { await service.arriveStop(this.data.taskId, stopId); wx.showToast({ title: '已记录到店', icon: 'success' }); await this.load() } catch (error) { await this.load(); this.setData({ error: error.message }) } finally { this.setData({ operating: false }) }
  },
  async perform(event) {
    if (this.data.operating) return
    const action = event.currentTarget.dataset.action
    if (action === 'complete' && !this.data.canComplete) return
    const text = action === 'start' ? '开始配送' : '完成配送'
    const confirmed = await new Promise((resolve) => wx.showModal({ title: '确认操作', content: '确认' + text + '当前整趟任务吗？', success: (result) => resolve(result.confirm) }))
    if (!confirmed) return
    this.setData({ operating: true, error: '' })
    try { if (action === 'start') await service.startTask(this.data.taskId); else await service.completeTask(this.data.taskId); wx.showToast({ title: text + '成功', icon: 'success' }); await this.load() } catch (error) { await this.load(); this.setData({ error: error.message }) } finally { this.setData({ operating: false }) }
  }
})
