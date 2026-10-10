const service = require('../../services/task')
const auth = require('../../utils/auth')

Page({
  data: {
    taskId: 0,
    stopId: 0,
    reasons: [
      { value: 'STORE_CLOSED', label: '门店关闭' },
      { value: 'REJECTED', label: '拒收' },
      { value: 'ADDRESS_ERROR', label: '地址错误' },
      { value: 'CARGO_DAMAGED', label: '货物损坏' },
      { value: 'OTHER', label: '其他' }
    ],
    reasonIndex: 0,
    remark: '',
    submitting: false,
    error: ''
  },
  onLoad(options) { this.setData({ taskId: Number(options.taskId), stopId: Number(options.stopId) }); auth.ensureLogin() },
  onReason(event) { this.setData({ reasonIndex: Number(event.detail.value) }) },
  onRemark(event) { this.setData({ remark: event.detail.value }) },
  async submit() {
    if (this.data.submitting) return
    const reason = this.data.reasons[this.data.reasonIndex]
    if (reason.value === 'OTHER' && !this.data.remark.trim()) { this.setData({ error: '选择其他时必须填写具体原因' }); return }
    const confirmed = await new Promise((resolve) => wx.showModal({ title: '确认配送失败', content: '提交后该门店将标记为已处理，确认继续吗？', success: (result) => resolve(result.confirm) }))
    if (!confirmed) return
    this.setData({ submitting: true, error: '' })
    try {
      await service.failStop(this.data.taskId, this.data.stopId, { failure_reason: reason.value, remark: this.data.remark.trim() || null })
      wx.showToast({ title: '异常已记录', icon: 'success' })
      setTimeout(() => wx.navigateBack(), 500)
    } catch (error) { this.setData({ error: error.message }) }
    finally { this.setData({ submitting: false }) }
  }
})
