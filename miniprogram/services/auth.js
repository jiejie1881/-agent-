const request = require('../utils/request')

function login(username, password) {
  return request({
    url: '/auth/login',
    method: 'POST',
    data: { username, password }
  })
}

function getProfile() { return request({ url: '/profile' }) }

module.exports = { login, getProfile }
