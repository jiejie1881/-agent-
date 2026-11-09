<script setup lang="ts">
import { businessRef } from '@/utils/businessLabels'
import { Edit, Link, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, ref } from 'vue'

import { createRoute, deleteRoute, listRoutes, updateRoute, listRouteStores } from '@/api/routes'
import { addStoreRoute, listStores, removeStoreRoute } from '@/api/stores'
import { useAuthStore } from '@/stores/auth'
import type { Route, RoutePayload } from '@/types/route'
import type { Store } from '@/types/store'
import RouteFormDialog from '@/views/routes/components/RouteFormDialog.vue'
import RouteStoreDialog from '@/views/routes/components/RouteStoreDialog.vue'
import {allPages} from '@/api/pagination'

interface RouteRow extends Route { stores: Store[] }
const authStore = useAuthStore()
const loading = ref(false), submitting = ref(false), relationSaving = ref(false)
const rows = ref<RouteRow[]>([]), stores = ref<Store[]>([]), keyword = ref('')
const dialogVisible = ref(false), relationVisible = ref(false)
const editing = ref<Route | null>(null), relationRoute = ref<RouteRow | null>(null)
const offset=ref(0),pageSize=50
async function page(delta:number){offset.value=Math.max(0,offset.value+delta);await loadData()}

async function loadData() {
  loading.value = true
  try {
    const [routeResponse, storeResponse] = await Promise.all([listRoutes({offset:offset.value,limit:pageSize,q:keyword.value || undefined}), allPages(listStores)])
    stores.value = storeResponse.data
    rows.value = await Promise.all(routeResponse.data.map(async route=>({...route,stores:(await listRouteStores(route.id)).data})))
  } catch {} finally { loading.value = false }
}
function openCreate() { editing.value = null; dialogVisible.value = true }
function openEdit(item: Route) { editing.value = item; dialogVisible.value = true }
function openRelations(item: RouteRow) { relationRoute.value = item; relationVisible.value = true }
async function submit(payload: RoutePayload) {
  submitting.value = true
  try { if (editing.value) { await updateRoute(editing.value.id, payload); ElMessage.success('线路修改成功') } else { await createRoute(payload); ElMessage.success('线路新增成功') }; dialogVisible.value = false; await loadData() } catch {} finally { submitting.value = false }
}
async function remove(item: RouteRow) {
  try { await ElMessageBox.confirm(`确认删除线路“${item.name}”吗？`, '删除线路', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }) } catch { return }
  try { await deleteRoute(item.id); ElMessage.success('线路删除成功'); await loadData() } catch {}
}
async function saveRelations(nextStoreIds: number[]) {
  if (!relationRoute.value) return
  relationSaving.value = true
  const routeId = relationRoute.value.id
  const original = relationRoute.value.stores.map((store) => store.id)
  try {
    for (const storeId of nextStoreIds.filter((id) => !original.includes(id))) await addStoreRoute(storeId, routeId)
    for (const storeId of original.filter((id) => !nextStoreIds.includes(id))) await removeStoreRoute(storeId, routeId)
    ElMessage.success('线路门店关系已更新')
    relationVisible.value = false
  } catch {} finally { relationSaving.value = false; await loadData() }
}
onMounted(loadData)
</script>

<template>
  <section class="master-page">
    <div class="page-heading"><div><p class="eyebrow">基础资料</p><h1>线路管理</h1><p>维护线路资料，并查看或调整线路关联门店。</p></div><el-button v-if="authStore.canManageMasterData" type="primary" :icon="Plus" @click="openCreate">新增线路</el-button></div>
    <el-card class="table-card" shadow="never">
      <div class="toolbar"><el-input v-model="keyword" :prefix-icon="Search" clearable placeholder="搜索中文编号、内部编码或名称" @keyup.enter="offset=0;loadData()" @clear="offset=0;loadData()" /><el-button @click="offset=0;loadData()">查询</el-button><el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button></div>
      <el-table v-loading="loading" :data="rows" row-key="id" stripe>
        <template #empty><el-empty description="暂无线路数据" :image-size="92" /></template>
        <el-table-column label="线路" min-width="190"><template #default="{ row }"><strong>{{ row.name }}</strong><div class="code">{{ businessRef('RT', row.id) }} · {{ row.code }}</div></template></el-table-column>
        <el-table-column prop="description" label="说明" min-width="220"><template #default="{ row }">{{ row.description || '—' }}</template></el-table-column>
        <el-table-column label="路线资料" min-width="240"><template #default="{row}">{{ row.start_address ?? '起点未录入' }} → {{ row.end_address ?? '终点未录入' }}<div>{{ row.distance_km ?? '距离未录入' }} km · {{ row.duration_minutes ?? '时间未录入' }} 分钟 · {{ row.route_data_source ?? '来源未录入' }}</div></template></el-table-column>
        <el-table-column label="关联门店" min-width="300"><template #default="{ row }"><div v-if="row.stores.length" class="tags"><el-tag v-for="store in row.stores" :key="store.id" effect="plain">{{ store.name }}</el-tag></div><span v-else class="muted">未关联门店</span></template></el-table-column>
        <el-table-column label="状态" width="100" align="center"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag></template></el-table-column>
        <el-table-column v-if="authStore.canManageMasterData" label="操作" width="220" align="center" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button><el-button link type="primary" :icon="Link" @click="openRelations(row)">门店</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
      </el-table><div class="summary">本页 {{ rows.length }} 条 · 第 {{ Math.floor(offset/pageSize)+1 }} 页</div><el-button :disabled="offset===0 || loading" @click="page(-pageSize)">上一页</el-button><el-button :disabled="rows.length<pageSize || loading" @click="page(pageSize)">下一页</el-button>
    </el-card>
    <RouteFormDialog v-if="authStore.canManageMasterData" v-model="dialogVisible" :route="editing" :submitting="submitting" @submit="submit" />
    <RouteStoreDialog v-if="authStore.canManageMasterData" v-model="relationVisible" :route="relationRoute" :stores="stores" :selected-store-ids="relationRoute?.stores.map((item) => item.id) ?? []" :saving="relationSaving" @save="saveRelations" />
  </section>
</template>

<style scoped>
.master-page { max-width: 1500px; margin: 0 auto; }.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 22px; }.eyebrow { margin: 0 0 7px !important; color: #2f80ed !important; font-size: 13px; font-weight: 600; }.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }.page-heading p { margin: 9px 0 0; color: #6b778c; }.table-card { border-color: #e4eaf2; border-radius: 14px; }.toolbar { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 18px; }.toolbar .el-input { width: 380px; }.code,.muted { margin-top: 4px; color: #8993a4; font-family: Consolas, monospace; font-size: 12px; }.tags { display: flex; flex-wrap: wrap; gap: 5px; }.summary { margin-top: 14px; color: #8993a4; font-size: 12px; text-align: right; }
</style>
