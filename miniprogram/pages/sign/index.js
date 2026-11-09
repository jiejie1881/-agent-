const service = require('../../services/task')
const auth = require('../../utils/auth')

Page({
  data: { taskId: 0, stopId: 0, replacesProofId: 0, stop: null, activeProofCount: 0, receiverName: '', receiverPhone: '', remark: '', media: [], submitting: false, error: '' },
  async onLoad(options) {
    this.setData({ taskId: Number(options.taskId), stopId: Number(options.stopId), replacesProofId: Number(options.replacesProofId) || 0 })
    if (!auth.ensureLogin()) return
    await this.refreshStop()
  },
  onShow() {
    if (this._sessionVersion !== undefined && this._sessionVersion !== auth.getSessionVersion()) {
      this.setData({ stop: null, activeProofCount: 0, receiverName: '', receiverPhone: '', remark: '', media: [], error: '登录状态已变化，请重新打开任务' })
      this._sessionChanged = true
    }
    auth.ensureLogin()
  },
  async refreshStop() {
    const version = auth.getSessionVersion()
    this._sessionVersion = version
    this.setData({ stop: null, activeProofCount: 0 })
    try {
      const stop = await service.hydrateProofs(await service.getStop(this.data.taskId, this.data.stopId))
      if (version !== auth.getSessionVersion()) return
      this.setData({ stop: stop, activeProofCount: stop.proofs.filter(proof => !proof.historical).length })
    } catch (error) { if (version === auth.getSessionVersion()) this.setData({ error: error.message }) }
  },
  onName(event) { this.setData({ receiverName: event.detail.value }) },
  onPhone(event) { this.setData({ receiverPhone: event.detail.value }) },
  onRemark(event) { this.setData({ remark: event.detail.value }) },
  async chooseMedia() {
    const remaining = (this.data.replacesProofId ? 1 : 3 - this.data.activeProofCount) - this.data.media.length
    if (remaining <= 0) { wx.showToast({ title: '最多上传3张', icon: 'none' }); return }
    try {
      const result = await wx.chooseMedia({ count: remaining, mediaType: ['image'], sourceType: ['album', 'camera'], sizeType: ['compressed'] })
      this.setData({ media: this.data.media.concat(result.tempFiles.map((item) => item.tempFilePath)) })
    } catch (error) {}
  },
  removeMedia(event) {
    const index = Number(event.currentTarget.dataset.index)
    this.setData({ media: this.data.media.filter((_item, itemIndex) => itemIndex !== index) })
  },
  async submit() {
    if (this.data.submitting) return
    if (!auth.ensureLogin()) return
    if (this._sessionChanged || (this._sessionVersion !== undefined && this._sessionVersion !== auth.getSessionVersion())) {
      this.onShow()
      return
    }
    if (!this.data.replacesProofId && !this.data.receiverName.trim()) { this.setData({ error: '请输入签收人姓名' }); return }
    if (this.data.replacesProofId && this.data.media.length !== 1) { this.setData({ error: '请选择1张补传照片' }); return }
    const version = auth.getSessionVersion()
    this.setData({ submitting: true, error: '' })
    try {
      while (this.data.media.length) {
        await service.uploadProof(this.data.taskId, this.data.stopId, this.data.media[0], this.data.replacesProofId || undefined)
        if (version !== auth.getSessionVersion()) return
        this.setData({ media: this.data.media.slice(1) })
      }
      if (!this.data.replacesProofId) await service.signStop(this.data.taskId, this.data.stopId, { receiver_name: this.data.receiverName.trim(), receiver_phone: this.data.receiverPhone.trim() || null, remark: this.data.remark.trim() || null })
      if (version !== auth.getSessionVersion()) return
      wx.showToast({ title: this.data.replacesProofId ? '补传成功' : '签收成功', icon: 'success' })
      setTimeout(() => { if (version === auth.getSessionVersion()) wx.navigateBack() }, 500)
    } catch (error) { if (version === auth.getSessionVersion()) { await this.refreshStop(); this.setData({ error: error.message }) } }
    finally { this.setData({ submitting: false }) }
  }
})
