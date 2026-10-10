const service = require('../../services/task')
const auth = require('../../utils/auth')
Page({
  data: { dateFrom: '', dateTo: '', items: [], total: 0, page: 1, pageSize: 20, loading: false, error: '' },
  onShow() { if (auth.ensureLogin()) this.load(true) },
  onPullDownRefresh() { this.load(true).finally(() => wx.stopPullDownRefresh()) },
  onReachBottom() { if (!this.data.loading && this.data.items.length < this.data.total) this.load(false) },
  onDateFrom(event) { this.setData({ dateFrom: event.detail.value }) },
  onDateTo(event) { this.setData({ dateTo: event.detail.value }) },
  search() { this.load(true) },
  async load(reset) {
    const page = reset ? 1 : this.data.page + 1
    this.setData({ loading: true, error: '' })
    try {
      const result = await service.getHistory({ start_date: this.data.dateFrom, end_date: this.data.dateTo, page: page, page_size: this.data.pageSize })
      this.setData({ items: reset ? result.items : this.data.items.concat(result.items), total: result.total, page: page })
    } catch (error) { this.setData({ error: error.message }) }
    finally { this.setData({ loading: false }) }
  },
  openTask(event) { wx.navigateTo({ url: '/pages/task-detail/index?id=' + event.currentTarget.dataset.id }) }
})
