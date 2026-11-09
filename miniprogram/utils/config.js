// 修改 ACTIVE_ENV 即可切换环境。lan/prod 地址保持为空，使用前必须显式填写，
// 避免把某位开发者的局域网地址或虚构的生产域名写进业务代码。
const ACTIVE_ENV = 'dev'
const ENVIRONMENTS = {
  dev: { serverBaseUrl: 'http://127.0.0.1:62112' },
  lan: { serverBaseUrl: '' },
  prod: { serverBaseUrl: '' }
}

const environment = ENVIRONMENTS[ACTIVE_ENV]
if (!environment || !environment.serverBaseUrl) {
  throw new Error('请在 miniprogram/utils/config.js 中配置当前环境的 SERVER_BASE_URL')
}

const SERVER_BASE_URL = environment.serverBaseUrl.replace(/\/$/, '')
const API_BASE_URL = SERVER_BASE_URL + '/api/driver'

module.exports = { ACTIVE_ENV, API_BASE_URL, SERVER_BASE_URL }
