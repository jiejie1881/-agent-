<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import type { Vehicle, VehiclePayload, VehicleType } from '@/types/vehicle'
import type { AuthUser } from '@/types/auth'

const props = defineProps<{ modelValue: boolean; vehicle: Vehicle | null; vehicleTypes: VehicleType[]; drivers: AuthUser[]; submitting: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; submit: [VehiclePayload] }>()
const formRef = ref<FormInstance>()
const form = reactive<VehiclePayload>({ code: '', plate_number: '', vehicle_type_id: 0, driver_user_id: null, is_active: true })
const title = computed(() => (props.vehicle ? '修改车辆' : '新增车辆'))
const rules: FormRules<VehiclePayload> = {
  code: [
    { required: true, message: '请输入车辆编码', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_-]+$/, message: '仅支持字母、数字、下划线和短横线', trigger: 'blur' },
    { max: 50, message: '编码不能超过50个字符', trigger: 'blur' },
  ],
  plate_number: [{ required: true, message: '请输入车牌号', trigger: 'blur' }, { max: 20, message: '车牌号不能超过20个字符', trigger: 'blur' }],
  vehicle_type_id: [{ required: true, type: 'number', min: 1, message: '请选择车型', trigger: 'change' }],
}
watch(() => props.modelValue, (visible) => {
  if (!visible) return
  Object.assign(form, {
    code: props.vehicle?.code ?? '', plate_number: props.vehicle?.plate_number ?? '',
    vehicle_type_id: props.vehicle?.vehicle_type_id ?? props.vehicleTypes[0]?.id ?? 0,
    driver_user_id: props.vehicle?.driver_user_id ?? null,
    is_active: props.vehicle?.is_active ?? true,
  })
  nextTick(() => formRef.value?.clearValidate())
})
async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  emit('submit', { ...form, code: form.code.trim().toUpperCase(), plate_number: form.plate_number.trim().toUpperCase() })
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="title" width="560px" destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="车辆编码" prop="code"><el-input v-model="form.code" maxlength="50" placeholder="例如：V001" /></el-form-item>
      <el-form-item label="车牌号" prop="plate_number"><el-input v-model="form.plate_number" maxlength="20" placeholder="例如：湘A001" /></el-form-item>
      <el-form-item label="车型" prop="vehicle_type_id"><el-select v-model="form.vehicle_type_id" style="width: 100%" placeholder="请选择车型"><el-option v-for="item in vehicleTypes" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" :disabled="!item.is_active" /></el-select></el-form-item>
      <el-form-item label="绑定司机"><el-select v-model="form.driver_user_id" clearable style="width: 100%" placeholder="暂不绑定"><el-option v-for="item in drivers" :key="item.id" :label="item.username" :value="item.id" :disabled="!item.is_active" /></el-select></el-form-item>
      <el-form-item label="启用状态"><el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" /></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">保存</el-button></template>
  </el-dialog>
</template>
