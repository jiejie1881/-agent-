<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Route } from '@/types/route'
import type { Store } from '@/types/store'

const props = defineProps<{ modelValue: boolean; route: Route | null; stores: Store[]; selectedStoreIds: number[]; saving: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; save: [number[]] }>()
const selection = ref<number[]>([])
const keyword = ref('')
const filtered = computed(() => {
  const value = keyword.value.trim().toLowerCase()
  return value ? props.stores.filter((store) => `${store.code} ${store.name}`.toLowerCase().includes(value)) : props.stores
})
watch(() => props.modelValue, (visible) => {
  if (!visible) return
  selection.value = [...props.selectedStoreIds]
  keyword.value = ''
})
</script>

<template>
  <el-dialog :model-value="modelValue" :title="`配置线路门店${route ? ` · ${route.name}` : ''}`" width="680px" destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <el-alert title="一个门店可关联多条线路；此处复用现有门店线路关系接口。" type="info" :closable="false" show-icon />
    <el-input v-model="keyword" class="search" clearable placeholder="搜索门店编码或名称" />
    <el-scrollbar height="340px" class="list">
      <el-checkbox-group v-model="selection">
        <div v-if="filtered.length" class="grid">
          <label v-for="store in filtered" :key="store.id" class="option">
            <el-checkbox :value="store.id"><span class="code">{{ store.code }}</span>{{ store.name }}</el-checkbox>
            <el-tag :type="store.is_active ? 'success' : 'info'" size="small" effect="plain">{{ store.is_active ? '启用' : '停用' }}</el-tag>
          </label>
        </div>
        <el-empty v-else description="暂无可选门店" :image-size="72" />
      </el-checkbox-group>
    </el-scrollbar>
    <template #footer><span class="count">已选择 {{ selection.length }} 个门店</span><el-button :disabled="saving" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="saving" @click="emit('save', selection)">保存关系</el-button></template>
  </el-dialog>
</template>

<style scoped>
.search { margin: 16px 0 12px; }.list { border: 1px solid #e6ebf2; border-radius: 8px; }.grid { padding: 8px; }.option { display: flex; align-items: center; justify-content: space-between; min-height: 48px; padding: 6px 10px; border-radius: 6px; }.option:hover { background: #f5f8fc; }.code { display: inline-block; min-width: 74px; margin-right: 8px; color: #52627a; font-family: Consolas, monospace; }.count { float: left; padding-top: 8px; color: #7a869a; font-size: 13px; }
</style>
