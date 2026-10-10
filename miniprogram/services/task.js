const request = require('../utils/request')
const { API_BASE_URL, SERVER_BASE_URL } = require('../utils/config')
const auth = require('../utils/auth')

function getTodayTasks() { return request({ url: '/tasks/today' }) }
function getTask(taskId) { return request({ url: '/tasks/' + taskId }) }
function startTask(taskId) { return request({ url: '/tasks/' + taskId + '/start', method: 'POST' }) }
function completeTask(taskId) { return request({ url: '/tasks/' + taskId + '/complete', method: 'POST' }) }
function getStop(taskId, stopId) { return request({ url: '/tasks/' + taskId + '/stops/' + stopId }) }
function arriveStop(taskId, stopId) { return request({ url: '/tasks/' + taskId + '/stops/' + stopId + '/arrive', method: 'POST' }) }
function signStop(taskId, stopId, data) { return request({ url: '/tasks/' + taskId + '/stops/' + stopId + '/sign', method: 'POST', data: data }) }
function failStop(taskId, stopId, data) { return request({ url: '/tasks/' + taskId + '/stops/' + stopId + '/fail', method: 'POST', data: data }) }
function uploadProof(taskId, stopId, filePath, replacesProofId) {
  if (!auth.ensureLogin()) return Promise.reject(new Error('请先登录司机账号'))
  const version = auth.getSessionVersion()
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: API_BASE_URL + '/tasks/' + taskId + '/stops/' + stopId + '/proofs',
      filePath: filePath,
      name: 'file',
      formData: replacesProofId ? { replaces_proof_id: String(replacesProofId) } : {},
      timeout: 30000,
      header: { Authorization: 'Bearer ' + auth.getToken() },
      success(response) {
        if (version !== auth.getSessionVersion()) { reject(new Error('登录状态已变化，请重新加载')); return }
        let body = {}
        try { body = JSON.parse(response.data || '{}') } catch (error) { reject(new Error('上传响应格式异常')); return }
        if (response.statusCode >= 200 && response.statusCode < 300) { resolve(body); return }
        if (response.statusCode === 401) { auth.clearSession(); auth.redirectToLogin() }
        reject(new Error(body.detail || '回单上传失败'))
      },
      fail(error) { reject(new Error(error.errMsg || '回单上传失败')) }
    })
  })
}
function downloadProof(proof) {
  if (!auth.ensureLogin()) return Promise.reject(new Error('请先登录司机账号'))
  // Never send the JWT to an arbitrary URL supplied by a response.
  if (!/^\/uploads\/delivery-proofs\/[a-f0-9]{32}\.(png|jpg|webp)$/.test(proof.url)) return Promise.reject(new Error('回单图片地址无效'))
  const version = auth.getSessionVersion()
  return new Promise((resolve, reject) => wx.downloadFile({
    url: SERVER_BASE_URL + proof.url,
    header: { Authorization: 'Bearer ' + auth.getToken() }, timeout: 30000,
    success(response) {
      if (version !== auth.getSessionVersion()) { reject(new Error('登录状态已变化')); return }
      if (response.statusCode === 200) { resolve(response.tempFilePath); return }
      if (response.statusCode === 401) { auth.clearSession(); auth.redirectToLogin() }
      reject(new Error('回单图片读取失败'))
    },
    fail() { reject(new Error('回单图片网络请求失败')) }
  }))
}
async function hydrateProofs(stop) {
  const replaced = stop.proofs.map(proof => proof.replaces_proof_id).filter(Boolean)
  stop.proofs = await Promise.all(stop.proofs.map(async proof => {
    const result = Object.assign({}, proof, {
      historical: replaced.includes(proof.id),
      review_label: ({ PENDING: '待审核', APPROVED: '已通过', REJECTED: '已驳回' })[proof.review_status] || '待审核',
      review_reason: (proof.reviews || []).map(review => review.reason).filter(Boolean).join('；')
    })
    try { result.full_url = await downloadProof(proof) } catch (error) { result.image_error = error.message }
    return result
  }))
  return stop
}
function getHistory(params) {
  const query = Object.keys(params || {})
    .filter((key) => params[key] !== '')
    .map((key) => encodeURIComponent(key) + '=' + encodeURIComponent(params[key]))
    .join('&')
  return request({ url: '/tasks/history' + (query ? '?' + query : '') })
}

module.exports = { getTodayTasks, getTask, startTask, completeTask, getStop, arriveStop, signStop, failStop, uploadProof, downloadProof, hydrateProofs, getHistory }
