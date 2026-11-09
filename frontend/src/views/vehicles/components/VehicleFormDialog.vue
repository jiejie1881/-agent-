<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import type { Vehicle, VehiclePayload, VehicleType } from '@/types/vehicle'
import type { AuthUser } from '@/types/auth'
import type { Route } from '@/types/route'

const props = defineProps<{ modelValue: boolean; vehicle: Vehicle | null; vehicleTypes: VehicleType[]; drivers: AuthUser[]; routes: Route[]; submitting: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; submit: [VehiclePayload] }>()
const formRef = ref<FormInstance>()
const form = reactive<VehiclePayload>({ code: '', plate_number: '', vehicle_type_id: 0, driver_user_id: null, is_active: true, organization:null,rated_load:null,daily_trip_limit:null,operating_status:'ACTIVE',allowed_route_ids:null })
const restricted = ref(false)
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
    organization:props.vehicle?.organization ?? null,rated_load:props.vehicle?.rated_load == null ? null : Number(props.vehicle.rated_load),
    daily_trip_limit:props.vehicle?.daily_trip_limit ?? null,operating_status:props.vehicle?.operating_status ?? 'ACTIVE',
    allowed_route_ids:props.vehicle?.allowed_route_ids ? [...props.vehicle.allowed_route_ids] : null,
  })
  nextTick(() => formRef.value?.clearValidate())
  restricted.value = props.vehicle?.allowed_route_ids != null
})
async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  emit('submit', { ...form, allowed_route_ids:restricted.value ? form.allowed_route_ids ?? [] : null, code: form.code.trim().toUpperCase(), plate_number: form.plate_number.trim().toUpperCase() })
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
      <el-form-item label="所属组织"><el-input v-model="form.organization" maxlength="100" /></el-form-item>
      <el-form-item label="额定载重 kg"><el-input-number v-model="form.rated_load" :min="0.01" :precision="2" placeholder="为空使用车型上限" /></el-form-item>
      <el-form-item label="每日趟次"><el-input-number v-model="form.daily_trip_limit" :min="1" :max="100" :precision="0" placeholder="选填" /></el-form-item>
      <el-form-item label="运行状态"><el-select v-model="form.operating_status"><el-option label="正常" value="ACTIVE" /><el-option label="维修" value="MAINTENANCE" /><el-option label="退役" value="RETIRED" /></el-select></el-form-item>
      <el-form-item label="线路范围"><el-switch v-model="restricted" active-text="限制线路" inactive-text="不额外限制" /></el-form-item>
      <el-form-item v-if="restricted" label="允许线路"><el-select v-model="form.allowed_route_ids" multiple><el-option v-for="r in routes" :key="r.id" :value="r.id" :label="r.name" :disabled="!r.is_active" /></el-select></el-form-item>
      <p>启用线路限制后未选线路，车辆不能参与派车。额定载重与车型上限取较小值。</p>
    </el-form>
    <template #footer><el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">保存</el-button></template>
  </el-dialog>
</template>
