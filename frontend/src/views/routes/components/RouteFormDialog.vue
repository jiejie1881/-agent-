<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import type { Route, RoutePayload } from '@/types/route'

const props = defineProps<{ modelValue: boolean; route: Route | null; submitting: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; submit: [RoutePayload] }>()
const formRef = ref<FormInstance>()
const form = reactive<RoutePayload>({ code: '', name: '', description: null, is_active: true, start_address:null, end_address:null, geographic_notes:null, distance_km:null, duration_minutes:null, route_data_source:null })
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
    start_address:props.route?.start_address ?? null, end_address:props.route?.end_address ?? null,
    geographic_notes:props.route?.geographic_notes ?? null, distance_km:props.route?.distance_km == null ? null : Number(props.route.distance_km),
    duration_minutes:props.route?.duration_minutes ?? null, route_data_source:props.route?.route_data_source ?? null,
  })
  nextTick(() => formRef.value?.clearValidate())
})

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  emit('submit', { ...form, code: form.code.trim().toUpperCase(), name: form.name.trim(), description: form.description?.trim() || null, is_active: form.is_active })
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="title" width="560px" destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="线路编码" prop="code"><el-input v-model="form.code" maxlength="50" placeholder="例如：R001" /></el-form-item>
      <el-form-item label="线路名称" prop="name"><el-input v-model="form.name" maxlength="100" /></el-form-item>
      <el-form-item label="说明" prop="description"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="500" show-word-limit /></el-form-item>
      <el-form-item label="启用状态"><el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" /></el-form-item>
      <el-form-item label="起点地址"><el-input v-model="form.start_address" maxlength="255" /></el-form-item>
      <el-form-item label="终点地址"><el-input v-model="form.end_address" maxlength="255" /></el-form-item>
      <el-form-item label="地理说明"><el-input v-model="form.geographic_notes" type="textarea" maxlength="2000" /></el-form-item>
      <el-form-item label="距离 km"><el-input-number v-model="form.distance_km" :min="0" :precision="2" /></el-form-item>
      <el-form-item label="时间 分钟"><el-input-number v-model="form.duration_minutes" :min="0" :max="100000" :precision="0" /></el-form-item>
      <el-form-item label="数据来源"><el-input v-model="form.route_data_source" maxlength="100" placeholder="填写距离或时间时必填，例如实测或人工录入" /></el-form-item>
      <p>系统不根据经纬度计算道路距离；这里的距离和时间由业务人员提供。</p>
    </el-form>
    <template #footer><el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">保存</el-button></template>
  </el-dialog>
</template>
