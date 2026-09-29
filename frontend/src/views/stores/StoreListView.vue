<script setup lang="ts">
import { Edit, Link, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { listRouteTerrainConfigs, listRoutes } from '@/api/routes'
import {
  addStoreRoute,
  createStore,
  deleteStore,
  listStoreRoutes,
  listStores,
  removeStoreRoute,
  updateStore,
} from '@/api/stores'
import type { Route, RouteTerrainConfig } from '@/types/route'
import type { Store, StoreListItem, StorePayload, StoreRouteDisplay } from '@/types/store'
import StoreFormDialog from '@/views/stores/components/StoreFormDialog.vue'
import StoreRouteDialog from '@/views/stores/components/StoreRouteDialog.vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

const loading = ref(false)
const submitting = ref(false)
const routeSaving = ref(false)
const stores = ref<StoreListItem[]>([])
const routes = ref<Route[]>([])
const keyword = ref('')

const formVisible = ref(false)
const editingStore = ref<Store | null>(null)
const routeDialogVisible = ref(false)
const routeStore = ref<StoreListItem | null>(null)

const filteredStores = computed(() => {
  const normalized = keyword.value.trim().toLowerCase()
  if (!normalized) return stores.value
  return stores.value.filter((store) =>
    [store.code, store.name, store.address, store.contact_name, store.contact_phone]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalized)),
  )
})

function today(): string {
  const date = new Date()
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function effectiveTerrain(configs: RouteTerrainConfig[]): string | null {
  const targetDate = today()
  const effective = configs
    .filter((config) => config.effective_date <= targetDate)
    .sort((left, right) => right.effective_date.localeCompare(left.effective_date))[0]
  return effective?.terrain.name ?? null
}

async function loadData() {
  loading.value = true
  try {
    const [storeResponse, routeResponse] = await Promise.all([
      listStores({ offset: 0, limit: 100 }),
      listRoutes({ offset: 0, limit: 100 }),
    ])
    routes.value = routeResponse.data

    const routeLinksByStore = await Promise.all(
      storeResponse.data.map(async (store) => ({
        store,
        links: (await listStoreRoutes(store.id)).data,
      })),
    )
    const routeIds = [
      ...new Set(routeLinksByStore.flatMap((item) => item.links.map((link) => link.route_id))),
    ]
    const terrainEntries = await Promise.all(
      routeIds.map(async (routeId) => {
        const configs = (await listRouteTerrainConfigs(routeId)).data
        return [routeId, effectiveTerrain(configs)] as const
      }),
    )
    const terrainByRoute = new Map<number, string | null>(terrainEntries)

    stores.value = routeLinksByStore.map(({ store, links }) => ({
      ...store,
      route_links: links.map<StoreRouteDisplay>((link) => ({
        ...link,
        terrain_name: terrainByRoute.get(link.route_id) ?? null,
      })),
    }))
  } catch {
    // Axios interceptor has already shown the backend error.
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingStore.value = null
  formVisible.value = true
}

function openEdit(store: StoreListItem) {
  editingStore.value = store
  formVisible.value = true
}

async function submitStore(payload: StorePayload) {
  submitting.value = true
  try {
    if (editingStore.value) {
      await updateStore(editingStore.value.id, payload)
      ElMessage.success('门店修改成功')
    } else {
      await createStore(payload)
      ElMessage.success('门店新增成功')
    }
    formVisible.value = false
    await loadData()
  } catch {
    // Keep the dialog open so the user can correct or retry the form.
  } finally {
    submitting.value = false
  }
}

async function toggleStoreStatus(store: StoreListItem) {
  const nextActive = !store.is_active
  try {
    await ElMessageBox.confirm(
      `确认${nextActive ? '启用' : '停用'}门店“${store.name}”吗？`,
      `${nextActive ? '启用' : '停用'}门店`,
      { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await updateStore(store.id, { is_active: nextActive })
    ElMessage.success(`门店已${nextActive ? '启用' : '停用'}`)
    await loadData()
  } catch {
    // Axios interceptor has already shown the backend error.
  }
}

async function handleDelete(store: StoreListItem) {
  try {
    await ElMessageBox.confirm(
      `删除后无法恢复。确认删除门店“${store.name}”吗？`,
      '删除门店',
      { type: 'error', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteStore(store.id)
    ElMessage.success('门店删除成功')
    await loadData()
  } catch {
    // Axios interceptor has already shown the backend error.
  }
}

function openRouteDialog(store: StoreListItem) {
  routeStore.value = store
  routeDialogVisible.value = true
}

async function saveStoreRoutes(nextRouteIds: number[]) {
  if (!routeStore.value) return
  routeSaving.value = true
  const storeId = routeStore.value.id
  const originalRouteIds = routeStore.value.route_links.map((item) => item.route_id)
  const additions = nextRouteIds.filter((id) => !originalRouteIds.includes(id))
  const removals = originalRouteIds.filter((id) => !nextRouteIds.includes(id))

  try {
    for (const routeId of additions) {
      await addStoreRoute(storeId, routeId)
    }
    for (const routeId of removals) {
      await removeStoreRoute(storeId, routeId)
    }
    ElMessage.success('门店线路关系已更新')
    routeDialogVisible.value = false
  } catch {
    // Reload below to reflect any relationship mutation accepted before failure.
  } finally {
    routeSaving.value = false
    await loadData()
  }
}

onMounted(loadData)
</script>

<template>
  <section class="store-page">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">基础资料</p>
        <h1>门店管理</h1>
        <p>维护门店资料、启停状态以及门店可使用的配送线路。</p>
      </div>
      <el-button v-if="authStore.canManageMasterData" type="primary" :icon="Plus" @click="openCreate">新增门店</el-button>
    </div>

    <el-card class="store-card" shadow="never">
      <div class="toolbar">
        <el-input
          v-model="keyword"
          :prefix-icon="Search"
          clearable
          placeholder="搜索编码、名称、地址或联系人"
          class="toolbar__search"
        />
        <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
      </div>

      <el-table v-loading="loading" :data="filteredStores" row-key="id" stripe>
        <template #empty>
          <el-empty :description="keyword ? '没有匹配的门店' : '暂无门店数据'" :image-size="92" />
        </template>

        <el-table-column label="门店" min-width="180" fixed="left">
          <template #default="{ row }">
            <div class="store-name">{{ row.name }}</div>
            <div class="store-code">{{ row.code }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="address" label="地址" min-width="210">
          <template #default="{ row }">{{ row.address || '—' }}</template>
        </el-table-column>
        <el-table-column label="联系人" min-width="145">
          <template #default="{ row }">
            <div>{{ row.contact_name || '—' }}</div>
            <div class="secondary-text">{{ row.contact_phone || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="关联线路" min-width="250">
          <template #default="{ row }">
            <div v-if="row.route_links.length" class="tag-list">
              <el-tag v-for="linkItem in row.route_links" :key="linkItem.id" effect="plain">
                {{ linkItem.route.name }}
              </el-tag>
            </div>
            <span v-else class="empty-cell">未关联线路</span>
          </template>
        </el-table-column>
        <el-table-column label="当前地形" min-width="190">
          <template #default="{ row }">
            <div v-if="row.route_links.length" class="terrain-list">
              <div v-for="linkItem in row.route_links" :key="linkItem.id">
                <span class="terrain-list__route">{{ linkItem.route.code }}</span>
                <el-tag :type="linkItem.terrain_name ? 'warning' : 'info'" size="small">
                  {{ linkItem.terrain_name || '未配置' }}
                </el-tag>
              </div>
            </div>
            <span v-else class="empty-cell">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="authStore.canManageMasterData" label="操作" width="286" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" :icon="Link" @click="openRouteDialog(row)">线路</el-button>
            <el-button link :type="row.is_active ? 'warning' : 'success'" @click="toggleStoreStatus(row)">
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-summary">共 {{ filteredStores.length }} 条门店数据，本页最多加载 100 条</div>
    </el-card>

    <StoreFormDialog
      v-if="authStore.canManageMasterData"
      v-model="formVisible"
      :store="editingStore"
      :submitting="submitting"
      @submit="submitStore"
    />
    <StoreRouteDialog
      v-if="authStore.canManageMasterData"
      v-model="routeDialogVisible"
      :store="routeStore"
      :routes="routes"
      :saving="routeSaving"
      @save="saveStoreRoutes"
    />
  </section>
</template>

<style scoped>
.store-page {
  max-width: 1600px;
  margin: 0 auto;
}

.page-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 22px;
}

.page-heading__eyebrow {
  margin: 0 0 7px;
  color: #2f80ed;
  font-size: 13px;
  font-weight: 600;
}

.page-heading h1 {
  margin: 0;
  color: #172b4d;
  font-size: 28px;
}

.page-heading p:not(.page-heading__eyebrow) {
  margin: 9px 0 0;
  color: #6b778c;
}

.store-card {
  border-color: #e4eaf2;
  border-radius: 14px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  margin-bottom: 18px;
}

.toolbar__search {
  width: 380px;
}

.store-name {
  color: #172b4d;
  font-weight: 600;
}

.store-code,
.secondary-text,
.empty-cell {
  color: #8993a4;
  font-size: 12px;
}

.store-code {
  margin-top: 3px;
  font-family: Consolas, monospace;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.terrain-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.terrain-list > div {
  display: flex;
  align-items: center;
  gap: 7px;
}

.terrain-list__route {
  min-width: 56px;
  color: #6b778c;
  font-family: Consolas, monospace;
  font-size: 12px;
}

.table-summary {
  margin-top: 14px;
  color: #8993a4;
  font-size: 12px;
  text-align: right;
}
</style>
