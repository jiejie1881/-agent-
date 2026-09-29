<script setup lang="ts">
import { Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { createTerrain, deleteTerrain, listTerrains, updateTerrain } from '@/api/terrains'
import { useAuthStore } from '@/stores/auth'
import type { Terrain, TerrainPayload } from '@/types/route'
import TerrainFormDialog from '@/views/terrains/components/TerrainFormDialog.vue'

const authStore = useAuthStore()
const loading = ref(false)
const submitting = ref(false)
const terrains = ref<Terrain[]>([])
const keyword = ref('')
const dialogVisible = ref(false)
const editing = ref<Terrain | null>(null)
const filtered = computed(() => {
  const value = keyword.value.trim().toLowerCase()
  return value ? terrains.value.filter((item) => `${item.code} ${item.name} ${item.description ?? ''}`.toLowerCase().includes(value)) : terrains.value
})

async function loadData() {
  loading.value = true
  try { terrains.value = (await listTerrains({ offset: 0, limit: 100 })).data } catch { /* interceptor */ } finally { loading.value = false }
}
function openCreate() { editing.value = null; dialogVisible.value = true }
function openEdit(item: Terrain) { editing.value = item; dialogVisible.value = true }
async function submit(payload: TerrainPayload) {
  submitting.value = true
  try {
    if (editing.value) { await updateTerrain(editing.value.id, payload); ElMessage.success('地形修改成功') }
    else { await createTerrain(payload); ElMessage.success('地形新增成功') }
    dialogVisible.value = false
    await loadData()
  } catch { /* interceptor */ } finally { submitting.value = false }
}
async function remove(item: Terrain) {
  try { await ElMessageBox.confirm(`确认删除地形“${item.name}”吗？`, '删除地形', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }) } catch { return }
  try { await deleteTerrain(item.id); ElMessage.success('地形删除成功'); await loadData() } catch { /* interceptor */ }
}
onMounted(loadData)
</script>

<template>
  <section class="master-page">
    <div class="page-heading"><div><p class="eyebrow">基础资料</p><h1>地形管理</h1><p>维护线路风控所使用的地形基础资料。</p></div><el-button v-if="authStore.canManageMasterData" type="primary" :icon="Plus" @click="openCreate">新增地形</el-button></div>
    <el-card class="table-card" shadow="never">
      <div class="toolbar"><el-input v-model="keyword" :prefix-icon="Search" clearable placeholder="搜索编码、名称或说明" /><el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button></div>
      <el-table v-loading="loading" :data="filtered" row-key="id" stripe>
        <template #empty><el-empty description="暂无地形数据" :image-size="92" /></template>
        <el-table-column prop="code" label="地形编码" min-width="150"><template #default="{ row }"><span class="code">{{ row.code }}</span></template></el-table-column>
        <el-table-column prop="name" label="地形名称" min-width="170"><template #default="{ row }"><strong>{{ row.name }}</strong></template></el-table-column>
        <el-table-column prop="description" label="说明" min-width="260"><template #default="{ row }">{{ row.description || '—' }}</template></el-table-column>
        <el-table-column label="状态" width="100" align="center"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag></template></el-table-column>
        <el-table-column v-if="authStore.canManageMasterData" label="操作" width="150" align="center" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
      </el-table>
      <div class="summary">共 {{ filtered.length }} 条地形数据</div>
    </el-card>
    <TerrainFormDialog v-if="authStore.canManageMasterData" v-model="dialogVisible" :terrain="editing" :submitting="submitting" @submit="submit" />
  </section>
</template>

<style scoped>
.master-page { max-width: 1500px; margin: 0 auto; }.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 22px; }.eyebrow { margin: 0 0 7px !important; color: #2f80ed !important; font-size: 13px; font-weight: 600; }.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }.page-heading p { margin: 9px 0 0; color: #6b778c; }.table-card { border-color: #e4eaf2; border-radius: 14px; }.toolbar { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 18px; }.toolbar .el-input { width: 380px; }.code { color: #52627a; font-family: Consolas, monospace; }.summary { margin-top: 14px; color: #8993a4; font-size: 12px; text-align: right; }
</style>
