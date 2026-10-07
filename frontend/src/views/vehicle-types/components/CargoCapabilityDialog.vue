<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listCargoCategories } from '@/api/cargo-categories'
import { listVehicleTypeCargoCapabilities, replaceVehicleTypeCargoCapabilities } from '@/api/vehicles'
import type { CargoCategory, VehicleTypeCargoCapabilityInput } from '@/types/cargo'
import type { VehicleType } from '@/types/vehicle'

const props = defineProps<{ modelValue: boolean; vehicleType: VehicleType | null }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; saved: [] }>()
type Row = CargoCategory & VehicleTypeCargoCapabilityInput
const rows = reactive<Row[]>([])
const loading = ref(false), submitting = ref(false)
async function load() {
  if (!props.vehicleType) return
  loading.value = true
  try {
    const [categories, capabilities] = await Promise.all([listCargoCategories(), listVehicleTypeCargoCapabilities(props.vehicleType.id)])
    const map = new Map(capabilities.data.map((x) => [x.cargo_category_id, x]))
    rows.splice(0, rows.length, ...categories.data.map((category) => {
      const capability = map.get(category.id)
      return { ...category, cargo_category_id: category.id, is_allowed: capability?.is_allowed ?? false, min_temperature: capability?.min_temperature == null ? null : Number(capability.min_temperature), max_temperature: capability?.max_temperature == null ? null : Number(capability.max_temperature) }
    }))
  } finally { loading.value = false }
}
async function save() {
  for (const row of rows) {
    if ((row.min_temperature === null) !== (row.max_temperature === null)) return ElMessage.error(`${row.name} 的温度上下限必须同时填写`)
    if (row.min_temperature !== null && row.max_temperature !== null && row.min_temperature > row.max_temperature) return ElMessage.error(`${row.name} 的最低温度不能大于最高温度`)
  }
  if (!props.vehicleType) return
  submitting.value = true
  try { await replaceVehicleTypeCargoCapabilities(props.vehicleType.id, rows.map(({ cargo_category_id, is_allowed, min_temperature, max_temperature }) => ({ cargo_category_id, is_allowed, min_temperature, max_temperature }))); ElMessage.success('车型运输能力已保存'); emit('update:modelValue', false); emit('saved') } catch {} finally { submitting.value = false }
}
watch(() => props.modelValue, (visible) => { if (visible) load() })
</script>

<template>
  <el-dialog :model-value="modelValue" :title="`${vehicleType?.name ?? ''} · 可运输货物`" width="760px" destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-alert title="温度范围表示该车型针对对应货物分类可提供的运输能力；无需温控时可留空。" type="info" :closable="false" show-icon />
    <el-table v-loading="loading" :data="rows" style="margin-top:14px">
      <el-table-column prop="name" label="货物分类" min-width="160"><template #default="{ row }"><strong>{{ row.name }}</strong><div>{{ row.code }}</div></template></el-table-column>
      <el-table-column label="允许运输" width="110"><template #default="{ row }"><el-switch v-model="row.is_allowed" :disabled="!row.is_active" /></template></el-table-column>
      <el-table-column label="最低温度℃" width="160"><template #default="{ row }"><el-input-number v-model="row.min_temperature" :disabled="!row.is_allowed" :precision="2" controls-position="right" /></template></el-table-column>
      <el-table-column label="最高温度℃" width="160"><template #default="{ row }"><el-input-number v-model="row.max_temperature" :disabled="!row.is_allowed" :precision="2" controls-position="right" /></template></el-table-column>
    </el-table>
    <template #footer><el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="submitting" @click="save">保存</el-button></template>
  </el-dialog>
</template>
