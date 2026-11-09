import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { getCurrentUser, login as loginRequest } from '@/api/auth'
import type { AuthUser } from '@/types/auth'

const TOKEN_KEY = 'logistics_dispatch_access_token'
const REFRESH_TOKEN_KEY = 'logistics_dispatch_refresh_token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) ?? '')
  const user = ref<AuthUser | null>(null)
  const initialized = ref(false)

  const isAuthenticated = computed(() => Boolean(token.value && user.value))
  const canManageMasterData = computed(() => user.value?.role === 'ADMIN')
  const canOperate = computed(
    () => user.value?.role === 'ADMIN' || user.value?.role === 'DISPATCHER',
  )

  async function login(username: string, password: string) {
    const response = await loginRequest(username, password)
    token.value = response.data.access_token
    user.value = response.data.user
    localStorage.setItem(TOKEN_KEY, token.value)
    localStorage.setItem(REFRESH_TOKEN_KEY, response.data.refresh_token)
    initialized.value = true
  }

  function logout() {
    token.value = ''
    user.value = null
    initialized.value = true
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  }

  async function initialize() {
    if (initialized.value) return
    if (!token.value) {
      initialized.value = true
      return
    }
    try {
      user.value = (await getCurrentUser()).data
      if (user.value.role === 'DRIVER') logout()
    } catch {
      logout()
    } finally {
      initialized.value = true
    }
  }

  return {
    token,
    user,
    initialized,
    isAuthenticated,
    canManageMasterData,
    canOperate,
    login,
    logout,
    initialize,
  }
})
