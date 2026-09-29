<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import type { Route, RoutePayload } from '@/types/route'

const props = defineProps<{ modelValue: boolean; route: Route | null; submitting: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; submit: [RoutePayload] }>()
const formRef = ref<FormInstance>()
const form = reactive<RoutePayload>({ code: '', name: '', description: null, is_active: true })
const title = computed(() => (props.route ? '修改线路' : '新增线路'))
const rules: FormRules<RoutePayload> = {
  code: [
    { required: true, message: '请输入线路编码', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_-]+$/, message: '仅支持字母、数字、下划线和短横线', trigger: 'blur' },
    { max: 50, message: '编码不能超过50个字符', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入线路名称', trigger: 'blur' }, { max: 100, message: '名称不能超过100个字符', trigger: 'blur' }],
  description: [{ max: 500, message: '说明不能超过500个字符', trigger: 'blur' }],
}

watch(() => props.modelValue, (visible) => {
  if (!visible) return
  Object.assign(form, {
    code: props.route?.code ?? '', name: props.route?.name ?? '',
    description: props.route?.description ?? null, is_active: props.route?.is_active ?? true,
  })
  nextTick(() => formRef.value?.clearValidate())
})

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  emit('submit', { code: form.code.trim().toUpperCase(), name: form.name.trim(), description: form.description?.trim() || null, is_active: form.is_active })
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="title" width="560px" destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="线路编码" prop="code"><el-input v-model="form.code" maxlength="50" placeholder="例如：R001" /></el-form-item>
      <el-form-item label="线路名称" prop="name"><el-input v-model="form.name" maxlength="100" /></el-form-item>
      <el-form-item label="说明" prop="description"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="500" show-word-limit /></el-form-item>
      <el-form-item label="启用状态"><el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" /></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">保存</el-button></template>
  </el-dialog>
</template>
