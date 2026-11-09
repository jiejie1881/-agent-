const request = require('../utils/request')
module.exports = {
  list: () => request({ url: '/leaves' }),
  submit: (data) => request({ url: '/leaves', method: 'POST', data }),
  withdraw: (id) => request({ url: '/leaves/' + id + '/withdraw', method: 'POST' })
}
