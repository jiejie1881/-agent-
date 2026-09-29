import http from '@/api/http'
import type {
  AuthUser,
  LoginResponse,
  UserCreatePayload,
  UserUpdatePayload,
} from '@/types/auth'

export function login(username: string, password: string) {
  return http.post<LoginResponse>('/auth/login', { username, password })
}

export function getCurrentUser() {
  return http.get<AuthUser>('/auth/me')
}

export function listUsers() {
  return http.get<AuthUser[]>('/users', { params: { offset: 0, limit: 100 } })
}

export function createUser(data: UserCreatePayload) {
  return http.post<AuthUser>('/users', data)
}

export function updateUser(userId: number, data: UserUpdatePayload) {
  return http.patch<AuthUser>(`/users/${userId}`, data)
}

export function changePassword(currentPassword: string, newPassword: string) {
  return http.post('/auth/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}
