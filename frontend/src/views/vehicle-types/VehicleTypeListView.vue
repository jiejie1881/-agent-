<script setup lang="ts">
import { Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { createVehicleType, deleteVehicleType, listVehicleTypes, updateVehicleType } from '@/api/vehicles'
import { useAuthStore } from '@/stores/auth'
import type { VehicleType, VehicleTypePayload } from '@/types/vehicle'
import VehicleTypeFormDialog from '@/views/vehicle-types/components/VehicleTypeFormDialog.vue'

const authStore = useAuthStore()
const loading = ref(false), submitting = ref(false), dialogVisible = ref(false)
const items = ref<VehicleType[]>([]), editing = ref<VehicleType | null>(null), keyword = ref('')
const filtered = computed(() => { const value = keyword.value.trim().toLowerCase(); return value ? items.value.filter((item) => `${item.code} ${item.name}`.toLowerCase().includes(value)) : items.value })
async function loadData() { loading.value = true; try { items.value = (await listVehicleTypes({ offset: 0, limit: 100 })).data } catch {} finally { loading.value = false } }
function openCreate() { editing.value = null; dialogVisible.value = true }
function openEdit(item: VehicleType) { editing.value = item; dialogVisible.value = true }
async function submit(payload: VehicleTypePayload) {
  submitting.value = true
  try { if (editing.value) { await updateVehicleType(editing.value.id, payload); ElMessage.success('车型修改成功') } else { await createVehicleType(payload); ElMessage.success('车型新增成功') }; dialogVisible.value = false; await loadData() } catch {} finally { submitting.value = false }
}
async function remove(item: VehicleType) {
  try { await ElMessageBox.confirm(`确认删除车型“${item.name}”吗？已被车辆使用时后端会拒绝删除。`, '删除车型', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }) } catch { return }
  try { await deleteVehicleType(item.id); ElMessage.success('车型删除成功'); await loadData() } catch {}
}
onMounted(loadData)
</script>

<template>
  <section class="master-page">
    <div class="page-heading"><div><p class="eyebrow">基础资料</p><h1>车型管理</h1><p>车型身份由 code 决定，载重范围作为独立业务参数维护。</p></div><el-button v-if="authStore.canManageMasterData" type="primary" :icon="Plus" @click="openCreate">新增车型</el-button></div>
    <el-card class="table-card" shadow="never">
      <div class="toolbar"><el-input v-model="keyword" :prefix-icon="Search" clearable placeholder="搜索车型编码或名称" /><el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button></div>
      <el-table v-loading="loading" :data="filtered" row-key="id" stripe>
        <template #empty><el-empty description="暂无车型数据" :image-size="92" /></template>
        <el-table-column label="车型" min-width="210"><template #default="{ row }"><strong>{{ row.name }}</strong><div class="code">{{ row.code }}</div></template></el-table-column>
        <el-table-column label="最低载重" min-width="150" align="right"><template #default="{ row }"><strong>{{ Number(row.min_load).toFixed(2) }}</strong></template></el-table-column>
        <el-table-column label="最高载重" min-width="150" align="right"><template #default="{ row }"><strong>{{ Number(row.max_load).toFixed(2) }}</strong></template></el-table-column>
        <el-table-column label="状态" width="100" align="center"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag></template></el-table-column>
        <el-table-column v-if="authStore.canManageMasterData" label="操作" width="150" align="center" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
      </el-table><div class="summary">共 {{ filtered.length }} 条车型数据</div>
    </el-card>
    <VehicleTypeFormDialog v-if="authStore.canManageMasterData" v-model="dialogVisible" :vehicle-type="editing" :submitting="submitting" @submit="submit" />
  </section>
</template>

<style scoped>
.master-page { max-width: 1500px; margin: 0 auto; }.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 22px; }.eyebrow { margin: 0 0 7px !important; color: #2f80ed !important; font-size: 13px; font-weight: 600; }.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }.page-heading p { margin: 9px 0 0; color: #6b778c; }.table-card { border-color: #e4eaf2; border-radius: 14px; }.toolbar { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 18px; }.toolbar .el-input { width: 380px; }.code { margin-top: 4px; color: #8993a4; font-family: Consolas, monospace; font-size: 12px; }.summary { margin-top: 14px; color: #8993a4; font-size: 12px; text-align: right; }
</style>
