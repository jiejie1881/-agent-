import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage } from 'element-plus'

interface BackendErrorBody {
  code?: string
  detail?: string | Array<{ msg?: string }>
  issues?: ApiErrorIssue[]
}

interface RetryableRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
}

interface RefreshResponse {
  access_token: string
  refresh_token: string
}

export interface ApiErrorIssue {
  code: string
  message: string
  order_id?: number
  delivery_demand_id?: number
  [key: string]: unknown
}

export interface ApiError {
  status?: number
  code?: string
  message: string
  issues?: ApiErrorIssue[]
}

function getErrorMessage(error: AxiosError<BackendErrorBody>): string {
  const code = error.response?.data?.code
  const status = error.response?.status
  const requestUrl = error.config?.url ?? ''
  const isAgentRequest = requestUrl.includes('/agent/')
  const detail = error.response?.data?.detail

  if (code === 'AGENT_MODEL_TIMEOUT' || status === 504 && isAgentRequest) {
    return '智能调度助手响应超时，请重试'
  }
  if (
    code === 'AGENT_MODEL_CONFIGURATION_ERROR' ||
    code === 'AGENT_MODEL_CONNECTION_ERROR' ||
    status === 503 && isAgentRequest
  ) {
    return typeof detail === 'string' ? detail : '智能调度助手当前不可用，请稍后重试'
  }
  if (code === 'AGENT_MODEL_RESPONSE_ERROR' || status === 502 && isAgentRequest) {
    return typeof detail === 'string'
      ? detail
      : '智能调度助手暂时无法完成查询，请稍后重试'
  }
  if (status === 404 && requestUrl.includes('/agent/conversations/')) {
    return '该会话不存在或无权访问'
  }
  if (status === 403 && isAgentRequest) {
    return '当前账号没有使用智能调度助手的权限'
  }

  if (typeof detail === 'string') {
    return detail
  }
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg).filter(Boolean).join('；') || '请求参数错误'
  }
  if (error.code === 'ECONNABORTED') {
    return '请求超时，请稍后重试'
  }
  if (!error.response) {
    return '无法连接后端服务'
  }
  return '请求失败，请稍后重试'
}

const http: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const refreshToken = localStorage.getItem('logistics_dispatch_refresh_token')
  if (!refreshToken) throw new Error('missing refresh token')
  const response = await axios.post<RefreshResponse>(`${apiBaseUrl}/auth/refresh`, {
    refresh_token: refreshToken,
  })
  localStorage.setItem('logistics_dispatch_access_token', response.data.access_token)
  localStorage.setItem('logistics_dispatch_refresh_token', response.data.refresh_token)
  return response.data.access_token
}

function clearAuthentication() {
  localStorage.removeItem('logistics_dispatch_access_token')
  localStorage.removeItem('logistics_dispatch_refresh_token')
}

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('logistics_dispatch_access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<BackendErrorBody>) => {
    const request = error.config as RetryableRequestConfig | undefined
    const isLoginOrRefresh = request?.url?.includes('/auth/login') || request?.url?.includes('/auth/refresh')
    if (error.response?.status === 401 && request && !request._retry && !isLoginOrRefresh) {
      request._retry = true
      try {
        refreshPromise ??= refreshAccessToken().finally(() => { refreshPromise = null })
        const token = await refreshPromise
        request.headers.Authorization = `Bearer ${token}`
        return http(request)
      } catch {
        clearAuthentication()
      }
    }
    const apiError: ApiError = {
      status: error.response?.status,
      code: error.response?.data?.code,
      message: getErrorMessage(error),
      issues: error.response?.data?.issues,
    }
    ElMessage.error(apiError.message)
    if (apiError.status === 401) {
      clearAuthentication()
      if (window.location.pathname !== '/login') window.location.assign('/login')
    }
    return Promise.reject(apiError)
  },
)

export default http
