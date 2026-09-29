<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import type { AuthUser, UserCreatePayload, UserRole, UserUpdatePayload } from '@/types/auth'

const props = defineProps<{ modelValue: boolean; user: AuthUser | null; currentUserId: number | null; submitting: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; submit: [UserCreatePayload | UserUpdatePayload] }>()
const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '', role: 'VIEWER' as UserRole, is_active: true })
const editingSelf = computed(() => props.user?.id === props.currentUserId)
const title = computed(() => (props.user ? '修改用户' : '创建用户'))
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }, { max: 100, message: '用户名不能超过100个字符', trigger: 'blur' }],
  password: [{ validator: (_rule, value, callback) => {
    if (!props.user && !value) return callback(new Error('请输入初始密码'))
    if (!props.user && value.length < 8) return callback(new Error('密码不能少于8位'))
    callback()
  }, trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}
watch(() => props.modelValue, (visible) => {
  if (!visible) return
  Object.assign(form, { username: props.user?.username ?? '', password: '', role: props.user?.role ?? 'VIEWER', is_active: props.user?.is_active ?? true })
  nextTick(() => formRef.value?.clearValidate())
})
async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  if (props.user) emit('submit', { username: form.username.trim(), role: form.role, is_active: form.is_active })
  else emit('submit', { username: form.username.trim(), password: form.password, role: form.role, is_active: form.is_active })
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="title" width="540px" destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-alert v-if="editingSelf" title="当前登录用户不能修改自己的角色或禁用自己。" type="warning" :closable="false" show-icon />
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px" :class="{ 'with-alert': editingSelf }">
      <el-form-item label="用户名" prop="username"><el-input v-model="form.username" maxlength="100" /></el-form-item>
      <el-form-item v-if="!user" label="初始密码" prop="password"><el-input v-model="form.password" type="password" show-password maxlength="200" autocomplete="new-password" /></el-form-item>
      <el-form-item label="角色" prop="role"><el-select v-model="form.role" :disabled="editingSelf" style="width: 100%"><el-option label="管理员（ADMIN）" value="ADMIN" /><el-option label="调度员（DISPATCHER）" value="DISPATCHER" /><el-option label="查看者（VIEWER）" value="VIEWER" /></el-select></el-form-item>
      <el-form-item label="启用状态"><el-switch v-model="form.is_active" :disabled="editingSelf" active-text="启用" inactive-text="禁用" /></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">保存</el-button></template>
  </el-dialog>
</template>

<style scoped>.with-alert { margin-top: 18px; }</style>
