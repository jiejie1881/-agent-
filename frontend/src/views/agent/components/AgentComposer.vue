<script setup lang="ts">
import { Promotion } from '@element-plus/icons-vue'
import { computed } from 'vue'

const props = defineProps<{
  modelValue: string
  sending: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
}>()

const canSend = computed(
  () => !props.sending && props.modelValue.trim().length > 0 && props.modelValue.length <= 4000,
)

function updateValue(value: string) {
  emit('update:modelValue', value)
}

function handleEnter(event: KeyboardEvent) {
  if (event.isComposing || event.shiftKey) return
  event.preventDefault()
  if (canSend.value) emit('send')
}
</script>

<template>
  <div class="composer">
    <div class="composer__input">
      <el-input
        :model-value="modelValue"
        type="textarea"
        :rows="2"
        :maxlength="4000"
        show-word-limit
        resize="none"
        placeholder="输入调度查询，Enter 发送，Shift + Enter 换行"
        :disabled="sending"
        @update:model-value="updateValue"
        @keydown.enter="handleEnter"
      />
      <el-button
        type="primary"
        :icon="Promotion"
        :loading="sending"
        :disabled="!canSend"
        @click="emit('send')"
      >
        发送
      </el-button>
    </div>
    <p>助手仅提供只读查询，回答以系统当前业务数据为准。</p>
  </div>
</template>

<style scoped>
.composer {
  padding: 15px 20px 12px;
  background: #fff;
  border-top: 1px solid #e4eaf2;
}

.composer__input {
  display: flex;
  max-width: 960px;
  align-items: flex-end;
  gap: 12px;
  margin: 0 auto;
}

.composer__input .el-button {
  min-width: 92px;
  height: 54px;
}

.composer :deep(.el-textarea__inner) {
  min-height: 54px !important;
  padding: 10px 14px 20px;
  line-height: 1.5;
  border-radius: 11px;
  box-shadow: 0 0 0 1px #d8e0eb inset;
}

.composer p {
  margin: 8px auto 0;
  color: #9aa4b2;
  font-size: 11px;
  text-align: center;
}
</style>
