<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import type { VehicleType, VehicleTypePayload } from '@/types/vehicle'

const props = defineProps<{ modelValue: boolean; vehicleType: VehicleType | null; submitting: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; submit: [VehicleTypePayload] }>()
const formRef = ref<FormInstance>()
const form = reactive<VehicleTypePayload>({ code: '', name: '', min_load: 1, max_load: 1, is_active: true })
const title = computed(() => (props.vehicleType ? '修改车型' : '新增车型'))
const rules: FormRules<VehicleTypePayload> = {
  code: [{ required: true, message: '请选择车型编码', trigger: 'change' }],
  name: [{ required: true, message: '请输入车型名称', trigger: 'blur' }, { max: 100, message: '名称不能超过100个字符', trigger: 'blur' }],
  min_load: [{ required: true, message: '请输入最低载重', trigger: 'blur' }, { type: 'number', min: 0.01, message: '最低载重必须大于0', trigger: 'blur' }],
  max_load: [
    { required: true, message: '请输入最高载重', trigger: 'blur' },
    { type: 'number', min: 0.01, message: '最高载重必须大于0', trigger: 'blur' },
    { validator: (_rule, value, callback) => value < form.min_load ? callback(new Error('最高载重不能小于最低载重')) : callback(), trigger: 'blur' },
  ],
}
watch(() => props.modelValue, (visible) => {
  if (!visible) return
  Object.assign(form, {
    code: props.vehicleType?.code ?? '', name: props.vehicleType?.name ?? '',
    min_load: Number(props.vehicleType?.min_load ?? 1), max_load: Number(props.vehicleType?.max_load ?? 1),
    is_active: props.vehicleType?.is_active ?? true,
  })
  nextTick(() => formRef.value?.clearValidate())
})
async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  emit('submit', { ...form, name: form.name.trim() })
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="title" width="590px" destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
      <el-form-item label="车型编码" prop="code"><el-input v-model="form.code" maxlength="50" placeholder="填写业务车型编码，字母、数字、下划线或短横线" /></el-form-item>
      <el-form-item label="车型名称" prop="name"><el-input v-model="form.name" maxlength="100" /></el-form-item>
      <div class="load-grid">
        <el-form-item label="最低载重" prop="min_load"><el-input-number v-model="form.min_load" :min="0.01" :precision="2" :step="1" controls-position="right" /></el-form-item>
        <el-form-item label="最高载重" prop="max_load"><el-input-number v-model="form.max_load" :min="0.01" :precision="2" :step="1" controls-position="right" /></el-form-item>
      </div>
      <el-form-item label="启用状态"><el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" /></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">保存</el-button></template>
  </el-dialog>
</template>

<style scoped>.load-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }.el-input-number { width: 100%; }</style>
