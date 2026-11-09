const service = require('../../services/task')
const auth = require('../../utils/auth')
const DEPOT = { latitude: 28.2044615, longitude: 112.8911692 }
Page({
  data: { task: null, markers: [], polyline: [], latitude: DEPOT.latitude, longitude: DEPOT.longitude, error: '' },
  async onLoad(options) {
    if (!auth.ensureLogin()) return
    try {
      const task = await service.getTask(Number(options.id))
      const locatedStops = task.stops.filter((item) => item.latitude !== null && item.longitude !== null)
      const points = [DEPOT].concat(locatedStops.map((item) => ({ latitude: Number(item.latitude), longitude: Number(item.longitude) })))
      this.setData({
        task: task,
        markers: [{ id: 0, latitude: DEPOT.latitude, longitude: DEPOT.longitude, title: '配送中心', label: { content: '仓', color: '#ffffff', bgColor: '#1769e0', padding: 5 } }].concat(locatedStops.map((item) => ({ id: item.sequence, latitude: Number(item.latitude), longitude: Number(item.longitude), title: item.store_name, label: { content: String(item.sequence), color: '#ffffff', bgColor: '#e67e22', padding: 5 } }))),
        polyline: [{ points: points, color: '#1769e0', width: 5, dottedLine: false }]
      })
    } catch (error) { this.setData({ error: error.message }) }
  },
  navigate(event) {
    const stop = this.data.task.stops.find((item) => item.sequence === Number(event.currentTarget.dataset.sequence))
    if (!stop || stop.latitude === null || stop.longitude === null) { wx.showToast({ title: '该门店暂无坐标', icon: 'none' }); return }
    wx.openLocation({ latitude: Number(stop.latitude), longitude: Number(stop.longitude), name: stop.store_name, address: stop.address || '' })
  }
})
