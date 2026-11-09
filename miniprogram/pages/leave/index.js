const service = require('../../services/leave')
const auth = require('../../utils/auth')
const statuses = { PENDING: '待审批', APPROVED: '已批准', REJECTED: '已驳回', CANCELLED: '已撤回' }
const periods = ['ALL_DAY', 'MORNING', 'AFTERNOON']
Page({
  data: { start_date: '', end_date: '', periodIndex: 0, periodLabels: ['全天', '上午', '下午'], leave_type: '', reason: '', records: [], loading: false, saving: false, error: '' },
  onShow() { if (auth.ensureLogin()) this.load() },
  onHide() { this.requestId = (this.requestId || 0) + 1 },
  onUnload() { this.onHide() },
  change(e) { this.setData({ [e.currentTarget.dataset.field]: e.detail.value }) },
  async load() {
    if (!auth.ensureLogin()) return
    const id = this.requestId = (this.requestId || 0) + 1
    this.setData({ loading: true, error: '', records: [] })
    try { const rows = await service.list(); if (id === this.requestId) this.setData({ records: rows.map(r => Object.assign({}, r, { statusLabel: statuses[r.status] || r.status, periodLabel: this.data.periodLabels[periods.indexOf(r.period)] })) }) }
    catch (e) { if (id === this.requestId) this.setData({ error: e.message || '加载失败' }) }
    finally { if (id === this.requestId) this.setData({ loading: false }) }
  },
  async submit() {
    if (this.data.saving || !auth.ensureLogin()) return
    const { start_date, end_date, leave_type, reason, periodIndex } = this.data
    if (!start_date || !end_date || end_date < start_date || !leave_type.trim() || !reason.trim()) { wx.showToast({ title: '请填写有效日期、类型和原因', icon: 'none' }); return }
    this.setData({ saving: true, error: '' })
    try { await service.submit({ start_date, end_date, period: periods[Number(periodIndex)], leave_type: leave_type.trim(), reason: reason.trim() }); this.setData({ reason: '' }); wx.showToast({ title: '已提交审批', icon: 'success' }); await this.load() }
    catch (e) { this.setData({ error: e.message || '提交失败' }) }
    finally { this.setData({ saving: false }) }
  },
  withdraw(e) {
    if (this.data.saving || !auth.ensureLogin()) return
    const id = e.currentTarget.dataset.id
    wx.showModal({ title: '撤回申请', content: '确定撤回待审批请假申请？', success: async result => {
      if (!result.confirm || this.data.saving) return
      this.setData({ saving: true, error: '' })
      try { await service.withdraw(id); await this.load() } catch (error) { this.setData({ error: error.message || '撤回失败' }) } finally { this.setData({ saving: false }) }
    } })
  }
})
