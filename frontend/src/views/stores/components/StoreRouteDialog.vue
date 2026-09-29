<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { Route } from '@/types/route'
import type { StoreListItem } from '@/types/store'

const props = defineProps<{
  modelValue: boolean
  store: StoreListItem | null
  routes: Route[]
  saving: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [routeIds: number[]]
}>()

const selectedRouteIds = ref<number[]>([])
const keyword = ref('')

const filteredRoutes = computed(() => {
  const normalized = keyword.value.trim().toLowerCase()
  if (!normalized) return props.routes
  return props.routes.filter(
    (route) =>
      route.code.toLowerCase().includes(normalized) ||
      route.name.toLowerCase().includes(normalized),
  )
})

watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    selectedRouteIds.value = props.store?.route_links.map((item) => item.route_id) ?? []
    keyword.value = ''
  },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="`配置门店线路${store ? ` · ${store.name}` : ''}`"
    width="680px"
    destroy-on-close
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      title="门店可关联多条线路；地形由线路当前生效的地形配置决定。"
      type="info"
      :closable="false"
      show-icon
    />
    <el-input v-model="keyword" class="route-search" clearable placeholder="搜索线路编码或名称" />

    <el-scrollbar height="340px" class="route-list">
      <el-checkbox-group v-model="selectedRouteIds">
        <div v-if="filteredRoutes.length" class="route-grid">
          <label v-for="route in filteredRoutes" :key="route.id" class="route-option">
            <el-checkbox :value="route.id">
              <span class="route-option__code">{{ route.code }}</span>
              <span>{{ route.name }}</span>
            </el-checkbox>
            <el-tag :type="route.is_active ? 'success' : 'info'" size="small" effect="plain">
              {{ route.is_active ? '启用' : '停用' }}
            </el-tag>
          </label>
        </div>
        <el-empty v-else description="暂无可选线路" :image-size="72" />
      </el-checkbox-group>
    </el-scrollbar>

    <template #footer>
      <span class="selected-count">已选择 {{ selectedRouteIds.length }} 条线路</span>
      <el-button :disabled="saving" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="emit('save', selectedRouteIds)">保存关系</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.route-search {
  margin: 16px 0 12px;
}

.route-list {
  border: 1px solid #e6ebf2;
  border-radius: 8px;
}

.route-grid {
  padding: 8px;
}

.route-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 48px;
  padding: 6px 10px;
  border-radius: 6px;
}

.route-option:hover {
  background: #f5f8fc;
}

.route-option__code {
  display: inline-block;
  min-width: 74px;
  margin-right: 8px;
  color: #52627a;
  font-family: Consolas, monospace;
}

.selected-count {
  float: left;
  padding-top: 8px;
  color: #7a869a;
  font-size: 13px;
}
</style>
