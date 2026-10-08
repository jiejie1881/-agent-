<script setup lang="ts">
import { Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { createUser, listUsers, updateUser } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import type { AuthUser, UserCreatePayload, UserRole, UserUpdatePayload } from '@/types/auth'
import UserFormDialog from '@/views/users/components/UserFormDialog.vue'

const authStore = useAuthStore()
const loading = ref(false), submitting = ref(false), dialogVisible = ref(false)
const users = ref<AuthUser[]>([]), editing = ref<AuthUser | null>(null), keyword = ref('')
const filtered = computed(() => { const value = keyword.value.trim().toLowerCase(); return value ? users.value.filter((item) => `${item.username} ${item.role}`.toLowerCase().includes(value)) : users.value })
const roleLabels = { ADMIN: '管理员', DISPATCHER: '调度员', VIEWER: '查看者', DRIVER: '司机' }
function roleLabel(role: UserRole) { return roleLabels[role] }
async function loadData() { loading.value = true; try { users.value = (await listUsers()).data } catch {} finally { loading.value = false } }
function openCreate() { editing.value = null; dialogVisible.value = true }
function openEdit(user: AuthUser) { editing.value = user; dialogVisible.value = true }
async function submit(payload: UserCreatePayload | UserUpdatePayload) {
  submitting.value = true
  try { if (editing.value) { await updateUser(editing.value.id, payload as UserUpdatePayload); ElMessage.success('用户修改成功') } else { await createUser(payload as UserCreatePayload); ElMessage.success('用户创建成功') }; dialogVisible.value = false; await loadData() } catch {} finally { submitting.value = false }
}
async function toggleActive(user: AuthUser) {
  const next = !user.is_active
  try { await ElMessageBox.confirm(`确认${next ? '启用' : '禁用'}用户“${user.username}”吗？`, `${next ? '启用' : '禁用'}用户`, { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }) } catch { return }
  try { await updateUser(user.id, { is_active: next }); ElMessage.success(`用户已${next ? '启用' : '禁用'}`); await loadData() } catch {}
}
onMounted(loadData)
</script>

<template>
  <section class="user-page">
    <div class="page-heading"><div><p class="eyebrow">系统管理</p><h1>用户与权限</h1><p>管理登录账号、启用状态和角色分配。</p></div><el-button type="primary" :icon="Plus" @click="openCreate">创建用户</el-button></div>
    <el-card class="table-card" shadow="never">
      <div class="toolbar"><el-input v-model="keyword" :prefix-icon="Search" clearable placeholder="搜索用户名或角色" /><el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button></div>
      <el-table v-loading="loading" :data="filtered" row-key="id" stripe>
        <template #empty><el-empty description="暂无用户数据" :image-size="92" /></template>
        <el-table-column prop="username" label="用户名" min-width="220"><template #default="{ row }"><strong>{{ row.username }}</strong><el-tag v-if="row.id === authStore.user?.id" class="self-tag" size="small" effect="plain">当前用户</el-tag></template></el-table-column>
        <el-table-column label="角色" min-width="180"><template #default="{ row }"><el-tag :type="row.role === 'ADMIN' ? 'danger' : row.role === 'DISPATCHER' ? 'primary' : 'info'">{{ roleLabel(row.role) }} / {{ row.role }}</el-tag></template></el-table-column>
        <el-table-column label="状态" width="110" align="center"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '禁用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="220" align="center" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button><el-button link :type="row.is_active ? 'warning' : 'success'" :disabled="row.id === authStore.user?.id" @click="toggleActive(row)">{{ row.is_active ? '禁用' : '启用' }}</el-button></template></el-table-column>
      </el-table><div class="summary">共 {{ filtered.length }} 个用户</div>
    </el-card>
    <UserFormDialog v-model="dialogVisible" :user="editing" :current-user-id="authStore.user?.id ?? null" :submitting="submitting" @submit="submit" />
  </section>
</template>

<style scoped>
.user-page { max-width: 1400px; margin: 0 auto; }.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 22px; }.eyebrow { margin: 0 0 7px !important; color: #2f80ed !important; font-size: 13px; font-weight: 600; }.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }.page-heading p { margin: 9px 0 0; color: #6b778c; }.table-card { border-color: #e4eaf2; border-radius: 14px; }.toolbar { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 18px; }.toolbar .el-input { width: 360px; }.self-tag { margin-left: 10px; }.summary { margin-top: 14px; color: #8993a4; font-size: 12px; text-align: right; }
</style>
