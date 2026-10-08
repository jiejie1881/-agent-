export type UserRole = 'ADMIN' | 'DISPATCHER' | 'VIEWER' | 'DRIVER'

export interface AuthUser {
  id: number
  username: string
  role: UserRole
  is_active: boolean
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  user: AuthUser
}

export interface UserCreatePayload {
  username: string
  password: string
  role: UserRole
  is_active: boolean
}

export interface UserUpdatePayload {
  username?: string
  role?: UserRole
  is_active?: boolean
}
