<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { nextTick, reactive, ref, watch } from 'vue'

const props = defineProps<{ modelValue: boolean; submitting: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; submit: [currentPassword: string, newPassword: string] }>()
const formRef = ref<FormInstance>()
const form = reactive({ currentPassword: '', newPassword: '', confirmation: '' })
const rules: FormRules = {
  currentPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [{ required: true, message: '请输入新密码', trigger: 'blur' }, { min: 8, message: '新密码不能少于8位', trigger: 'blur' }],
  confirmation: [{ validator: (_rule, value, callback) => value !== form.newPassword ? callback(new Error('两次输入的新密码不一致')) : callback(), trigger: 'blur' }],
}
watch(() => props.modelValue, (visible) => {
  if (!visible) return
  Object.assign(form, { currentPassword: '', newPassword: '', confirmation: '' })
  nextTick(() => formRef.value?.clearValidate())
})
async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  emit('submit', form.currentPassword, form.newPassword)
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="修改密码" width="500px" destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-alert title="密码修改成功后，所有已签发的 Access Token 和 Refresh Token 都会失效，需要重新登录。" type="info" :closable="false" show-icon />
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px" class="password-form">
      <el-form-item label="当前密码" prop="currentPassword"><el-input v-model="form.currentPassword" type="password" show-password autocomplete="current-password" /></el-form-item>
      <el-form-item label="新密码" prop="newPassword"><el-input v-model="form.newPassword" type="password" show-password autocomplete="new-password" /></el-form-item>
      <el-form-item label="确认新密码" prop="confirmation"><el-input v-model="form.confirmation" type="password" show-password autocomplete="new-password" /></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">修改密码</el-button></template>
  </el-dialog>
</template>

<style scoped>.password-form { margin-top: 20px; }</style>
