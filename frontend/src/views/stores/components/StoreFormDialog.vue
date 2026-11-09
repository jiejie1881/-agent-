<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import type { Store, StorePayload } from '@/types/store'

const props = defineProps<{
  modelValue: boolean
  store: Store | null
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: StorePayload]
}>()

const formRef = ref<FormInstance>()
const form = reactive<StorePayload>({
  code: '',
  name: '',
  address: null,
  contact_name: null,
  contact_phone: null,
  delivery_region: null,
  longitude: null,
  latitude: null,
  is_active: true,
})

const rules: FormRules<StorePayload> = {
  code: [
    { required: true, message: '请输入门店编码', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_-]+$/, message: '仅支持字母、数字、下划线和短横线', trigger: 'blur' },
    { max: 50, message: '门店编码不能超过50个字符', trigger: 'blur' },
  ],
  name: [
    { required: true, message: '请输入门店名称', trigger: 'blur' },
    { max: 100, message: '门店名称不能超过100个字符', trigger: 'blur' },
  ],
  address: [{ max: 255, message: '地址不能超过255个字符', trigger: 'blur' }],
  contact_name: [{ max: 100, message: '联系人不能超过100个字符', trigger: 'blur' }],
  contact_phone: [{ max: 30, message: '联系电话不能超过30个字符', trigger: 'blur' }],
}

const title = computed(() => (props.store ? '修改门店' : '新增门店'))

function resetForm() {
  const source = props.store
  Object.assign(form, {
    code: source?.code ?? '',
    name: source?.name ?? '',
    address: source?.address ?? null,
    contact_name: source?.contact_name ?? null,
    contact_phone: source?.contact_phone ?? null,
    delivery_region: source?.delivery_region ?? null,
    longitude: source?.longitude == null ? null : Number(source.longitude),
    latitude: source?.latitude == null ? null : Number(source.latitude),
    is_active: source?.is_active ?? true,
  })
  nextTick(() => formRef.value?.clearValidate())
}

function normalizeOptional(value: string | null): string | null {
  const normalized = value?.trim()
  return normalized || null
}

async function handleSubmit() {
  if (!(await formRef.value?.validate().catch(() => false))) {
    return
  }
  emit('submit', {
    code: form.code.trim().toUpperCase(),
    name: form.name.trim(),
    address: normalizeOptional(form.address),
    contact_name: normalizeOptional(form.contact_name),
    contact_phone: normalizeOptional(form.contact_phone),
    delivery_region: normalizeOptional(form.delivery_region ?? null),
    longitude: form.longitude,
    latitude: form.latitude,
    is_active: form.is_active,
  })
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) resetForm()
  },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="620px"
    destroy-on-close
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
      <div class="form-grid">
        <el-form-item label="门店编码" prop="code">
          <el-input v-model="form.code" maxlength="50" placeholder="例如：S001" />
        </el-form-item>
        <el-form-item label="门店名称" prop="name">
          <el-input v-model="form.name" maxlength="100" placeholder="请输入门店名称" />
        </el-form-item>
        <el-form-item class="form-grid__full" label="门店地址" prop="address">
          <el-input v-model="form.address" maxlength="255" placeholder="请输入门店地址" />
        </el-form-item>
        <el-form-item label="联系人" prop="contact_name">
          <el-input v-model="form.contact_name" maxlength="100" placeholder="选填" />
        </el-form-item>
        <el-form-item label="联系电话" prop="contact_phone">
          <el-input v-model="form.contact_phone" maxlength="30" placeholder="选填" />
        </el-form-item>
        <el-form-item label="经度" prop="longitude">
          <el-input-number v-model="form.longitude" :min="-180" :max="180" :precision="7" controls-position="right" placeholder="选填" />
        </el-form-item>
        <el-form-item label="配送区域" prop="delivery_region"><el-input v-model="form.delivery_region" maxlength="100" placeholder="选填" /></el-form-item>
        <el-form-item label="纬度" prop="latitude">
          <el-input-number v-model="form.latitude" :min="-90" :max="90" :precision="7" controls-position="right" placeholder="选填" />
        </el-form-item>
        <el-form-item class="form-grid__full" label="启用状态" prop="is_active">
          <el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </div>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.form-grid__full {
  grid-column: 1 / -1;
}
</style>
