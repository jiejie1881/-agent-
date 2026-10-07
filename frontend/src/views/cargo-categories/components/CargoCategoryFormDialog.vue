<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { nextTick, reactive, ref, watch } from 'vue'
import type { CargoCategory, CargoCategoryPayload } from '@/types/cargo'

const props = defineProps<{ modelValue: boolean; item: CargoCategory | null; submitting: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; submit: [CargoCategoryPayload] }>()
const formRef = ref<FormInstance>()
const form = reactive<CargoCategoryPayload>({ code: '', name: '', description: null, is_active: true })
const rules: FormRules<CargoCategoryPayload> = {
  code: [{ required: true, pattern: /^[A-Za-z0-9_-]+$/, message: '请输入有效编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
}
watch(() => props.modelValue, (visible) => {
  if (!visible) return
  Object.assign(form, props.item ? {
    code: props.item.code, name: props.item.name,
    description: props.item.description, is_active: props.item.is_active,
  } : { code: '', name: '', description: null, is_active: true })
  nextTick(() => formRef.value?.clearValidate())
})
async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  emit('submit', { ...form, code: form.code.trim().toUpperCase(), name: form.name.trim() })
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="item ? '编辑货物分类' : '新增货物分类'" width="520px" destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="编码" prop="code"><el-input v-model="form.code" maxlength="50" /></el-form-item>
      <el-form-item label="名称" prop="name"><el-input v-model="form.name" maxlength="100" /></el-form-item>
      <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="500" show-word-limit /></el-form-item>
      <el-form-item label="状态"><el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" /></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">保存</el-button></template>
  </el-dialog>
</template>
