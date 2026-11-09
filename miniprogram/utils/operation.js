// Durable pending keys are scoped to the logged-in driver. The server binds
// the actual payload with SHA256; this local marker is not a security check.
function marker(value) {
  const text = JSON.stringify(value)
  let a = 2166136261, b = 5381
  for (let i = 0; i < text.length; i++) {
    a = Math.imul(a ^ text.charCodeAt(i), 16777619)
    b = Math.imul(b, 33) ^ text.charCodeAt(i)
  }
  return (a >>> 0).toString(16) + ':' + (b >>> 0).toString(16) + ':' + text.length
}
function begin(platform, operation, taskId, stopId, parameters) {
  const user = platform.getStorageSync('driver_user')
  if (!user || !user.id) throw new Error('请重新登录司机账号')
  const storageKey = 'driver_pending_operations_v1:' + user.id
  const entries = platform.getStorageSync(storageKey) || {}
  const slot = operation + ':' + taskId + ':' + stopId + ':' + marker(parameters)
  if (entries[slot]) return { storageKey, slot, key: entries[slot], reused: true }
  if (Object.keys(entries).length >= 2000) throw new Error('待核对操作过多，请先核对未完成操作')
  const key = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
  entries[slot] = key
  try { platform.setStorageSync(storageKey, entries) } catch (error) { throw new Error('无法保存重试凭据，请检查本机存储') }
  return { storageKey, slot, key, reused: false }
}
function complete(platform, pending) {
  const entries = platform.getStorageSync(pending.storageKey) || {}
  if (entries[pending.slot] === pending.key) {
    delete entries[pending.slot]
    // A cleanup error must not turn a confirmed successful business write into
    // a failed write. Retaining the key is safe: a retry returns the receipt.
    try { platform.setStorageSync(pending.storageKey, entries) } catch (error) {}
  }
}
module.exports = { begin, complete }
