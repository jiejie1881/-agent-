<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import type { DeliveryDemand, DeliveryDemandPayload } from '@/types/delivery-demand'
import type { Store } from '@/types/store'

const props = defineProps<{
  modelValue: boolean
  demand: DeliveryDemand | null
  defaultDate: string
  stores: Store[]
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: DeliveryDemandPayload]
}>()

const formRef = ref<FormInstance>()
const form = reactive<DeliveryDemandPayload>({
  date: '',
  store_id: 0,
  period: 'MORNING',
  quantity: 1,
  priority: 'NORMAL',
})

const isEdit = computed(() => props.demand !== null)
const fieldsDisabled = computed(
  () => isEdit.value && props.demand?.core_fields_editable !== true,
)
const title = computed(() => (isEdit.value ? '编辑配送需求' : '新增配送需求'))

const rules: FormRules<DeliveryDemandPayload> = {
  date: [{ required: true, message: '请选择配送日期', trigger: 'change' }],
  store_id: [{ required: true, type: 'number', min: 1, message: '请选择门店', trigger: 'change' }],
  period: [{ required: true, message: '请选择配送时段', trigger: 'change' }],
  quantity: [{ required: true, type: 'number', min: 0.01, message: '货量必须大于0', trigger: 'blur' }],
  priority: [{ required: true, message: '请选择优先级', trigger: 'change' }],
}

function resetForm() {
  Object.assign(form, {
    date: props.demand?.date ?? props.defaultDate,
    store_id: props.demand?.store_id ?? 0,
    period: props.demand?.period ?? 'MORNING',
    quantity: props.demand ? Number(props.demand.quantity) : 1,
    priority: props.demand?.priority ?? 'NORMAL',
  })
  nextTick(() => formRef.value?.clearValidate())
}

async function submit() {
  if (fieldsDisabled.value) return
  if (!(await formRef.value?.validate().catch(() => false))) return
  emit('submit', {
    ...form,
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
    width="560px"
    destroy-on-close
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      v-if="fieldsDisabled"
      title="该需求已进入派车流程，后端已锁定核心字段。请先按业务流程撤回后再修改。"
      type="warning"
      :closable="false"
      show-icon
      class="locked-alert"
    />
    <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
      <el-form-item label="配送日期" prop="date">
        <el-date-picker
          v-model="form.date"
          type="date"
          value-format="YYYY-MM-DD"
          :disabled="fieldsDisabled"
          :clearable="false"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="配送门店" prop="store_id">
        <el-select v-model="form.store_id" filterable :disabled="fieldsDisabled" placeholder="请选择门店" style="width: 100%">
          <el-option
            v-for="store in stores"
            :key="store.id"
            :label="`${store.code} · ${store.name}`"
            :value="store.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="配送时段" prop="period">
        <el-radio-group v-model="form.period" :disabled="fieldsDisabled">
          <el-radio-button value="MORNING">上午</el-radio-button>
          <el-radio-button value="AFTERNOON">下午</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="配送货量" prop="quantity">
        <el-input-number
          v-model="form.quantity"
          :disabled="fieldsDisabled"
          :min="0.01"
          :max="9999999999.99"
          :precision="2"
          controls-position="right"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="优先级" prop="priority"><el-radio-group v-model="form.priority" :disabled="fieldsDisabled"><el-radio-button value="NORMAL">普通</el-radio-button><el-radio-button value="HIGH">高</el-radio-button><el-radio-button value="URGENT">加急</el-radio-button></el-radio-group></el-form-item>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button v-if="!fieldsDisabled" type="primary" :loading="submitting" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.locked-alert { margin-bottom: 18px; }
</style>
