<script setup lang="ts">
import { Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { createVehicle, deleteVehicle, listVehicles, listVehicleTypes, updateVehicle } from '@/api/vehicles'
import { listUsers } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import type { Vehicle, VehiclePayload, VehicleType } from '@/types/vehicle'
import type { AuthUser } from '@/types/auth'
import VehicleFormDialog from '@/views/vehicles/components/VehicleFormDialog.vue'
import { fetchEnterpriseOverview, type EnterpriseOverview } from '@/api/enterprise'
import { typeLabel } from '@/utils/businessLabels'

const authStore = useAuthStore()
const loading = ref(false), submitting = ref(false), dialogVisible = ref(false)
const vehicles = ref<Vehicle[]>([]), vehicleTypes = ref<VehicleType[]>([]), editing = ref<Vehicle | null>(null), keyword = ref('')
const drivers = ref<AuthUser[]>([])
const day = ref(new Date().toLocaleDateString('sv-SE')), enterprise = ref<EnterpriseOverview | null>(null), statusError = ref('')
let requestVersion = 0
const operational = (id: number) => enterprise.value?.vehicles.find(v => v.id === id)
async function allPages<T>(fetchPage: (params: {offset: number; limit: number}) => Promise<{data: T[]}>) {
  const rows: T[] = []
  for (let offset = 0; ; offset += 100) { const {data} = await fetchPage({offset,limit:100}); rows.push(...data); if (data.length < 100) return rows }
}
const selectedTypeId = ref<number | null>(null)
const filtered = computed(() => {
  const value = keyword.value.trim().toLowerCase()
  return vehicles.value.filter((item) => (!selectedTypeId.value || item.vehicle_type_id === selectedTypeId.value) && (!value || `${item.code} ${item.plate_number} ${typeLabel(item.vehicle_type.code,item.vehicle_type.name)} ${operational(item.id)?.default_driver?.name ?? ''}`.toLowerCase().includes(value)))
})
async function loadData() {
  loading.value = true
  const version = ++requestVersion
  enterprise.value = null; statusError.value = ''
  try {
    const [vehicleRows, typeRows] = await Promise.all([allPages<Vehicle>(listVehicles), allPages<VehicleType>(listVehicleTypes)])
    if (version !== requestVersion) return
    vehicles.value = vehicleRows
    vehicleTypes.value = typeRows
    try { const {data} = await fetchEnterpriseOverview(day.value); if (version === requestVersion) enterprise.value = data }
    catch { if (version === requestVersion) statusError.value = '当日运营状态加载失败，可重试；基础资料仍可查看。' }
    if (authStore.canManageMasterData) drivers.value = (await listUsers()).data.filter((item) => item.role === 'DRIVER')
  } catch (e) { if (version === requestVersion) statusError.value = e && typeof e === 'object' && 'message' in e ? String(e.message) : '车辆资料加载失败，请刷新重试' }
  finally { if (version === requestVersion) loading.value = false }
}
function openCreate() { editing.value = null; dialogVisible.value = true }
function openEdit(item: Vehicle) { editing.value = item; dialogVisible.value = true }
async function submit(payload: VehiclePayload) {
  submitting.value = true
  try { if (editing.value) { await updateVehicle(editing.value.id, payload); ElMessage.success('车辆修改成功') } else { await createVehicle(payload); ElMessage.success('车辆新增成功') }; dialogVisible.value = false; await loadData() } catch {} finally { submitting.value = false }
}
async function remove(item: Vehicle) {
  try { await ElMessageBox.confirm(`确认删除车辆“${item.plate_number}”吗？存在业务引用时后端会拒绝。`, '删除车辆', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }) } catch { return }
  try { await deleteVehicle(item.id); ElMessage.success('车辆删除成功'); await loadData() } catch {}
}
onMounted(loadData)
</script>

<template>
  <section class="master-page">
    <div class="page-heading"><div><p class="eyebrow">基础资料</p><h1>车辆管理</h1><p>维护车辆、所属车型和启用状态。</p></div><el-button v-if="authStore.canManageMasterData" type="primary" :icon="Plus" :disabled="!vehicleTypes.length" @click="openCreate">新增车辆</el-button></div>
    <el-card class="table-card" shadow="never">
      <el-alert v-if="statusError" :title="statusError" type="error" :closable="false" />
      <p>运营日期：<el-date-picker v-model="day" value-format="YYYY-MM-DD" :clearable="false" @change="loadData" />　载重单位 kg；当日线路来自已发布任务，不代表车辆固定归属。</p>
      <div class="toolbar"><div class="filters"><el-input v-model="keyword" :prefix-icon="Search" clearable placeholder="搜索车辆编码、车牌号或车型" /><el-select v-model="selectedTypeId" clearable placeholder="全部车型"><el-option v-for="item in vehicleTypes" :key="item.id" :label="item.name" :value="item.id" /></el-select></div><el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button></div>
      <el-table v-loading="loading" :data="filtered" row-key="id" stripe>
        <template #empty><el-empty description="暂无车辆数据" :image-size="92" /></template>
        <el-table-column label="车辆" min-width="190"><template #default="{ row }"><strong>{{ row.plate_number }}</strong><div class="code">{{ row.code }}</div></template></el-table-column>
        <el-table-column label="车型" min-width="210"><template #default="{ row }"><div>{{ typeLabel(row.vehicle_type.code,row.vehicle_type.name) }}</div><div class="code">{{ row.vehicle_type.code }}</div></template></el-table-column>
        <el-table-column label="载重范围" min-width="190" align="center"><template #default="{ row }">{{ Number(row.vehicle_type.min_load).toFixed(2) }} ～ {{ Number(row.vehicle_type.max_load).toFixed(2) }}</template></el-table-column>
        <el-table-column label="常驻司机" min-width="150"><template #default="{ row }">{{ operational(row.id)?.default_driver?.name ?? (row.driver_user_id ? '资料未加载' : '未绑定') }}<div class="code">{{ operational(row.id)?.default_driver?.employee_code }}</div></template></el-table-column>
        <el-table-column label="当日出勤 / 可调度条件" min-width="230"><template #default="{row}">{{ !operational(row.id) ? '资料未加载' : operational(row.id)?.attendance === true ? '出勤' : operational(row.id)?.attendance === false ? '不出勤' : '未登记' }}<div v-for="p in ['MORNING','AFTERNOON']" :key="p">{{ p === 'MORNING' ? '上午' : '下午' }}：{{ operational(row.id)?.shifts[p]?.driver?.name ?? (operational(row.id) ? '无有效司机' : '资料未加载') }}<el-tag :type="operational(row.id)?.shifts[p]?.availability_status === 'AVAILABLE' ? 'success' : 'info'">{{ operational(row.id)?.shifts[p]?.availability_status === 'AVAILABLE' ? '司机/出勤就绪' : operational(row.id)?.shifts[p]?.unavailable_reason ?? '未加载' }}</el-tag></div></template></el-table-column>
        <el-table-column label="已发布任务 / 当前执行" min-width="230"><template #default="{row}"><div v-for="t in operational(row.id)?.tasks" :key="t.id"><router-link :to="`/dispatch/plans/${t.plan_id}`">{{ t.code }}</router-link> · {{ t.status === 'DELIVERING' ? '配送中' : t.status === 'COMPLETED' ? '已完成' : '待开始' }}<div>{{ t.route_name }} · {{ t.total_load }} kg · {{ t.driver?.name ?? '司机未记录' }}</div></div><span v-if="!operational(row.id)?.tasks.length">{{ operational(row.id) ? '暂无已发布任务' : '任务资料未加载' }}</span></template></el-table-column>
        <el-table-column label="状态" width="100" align="center"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag></template></el-table-column>
        <el-table-column v-if="authStore.canManageMasterData" label="操作" width="150" align="center" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
      </el-table><div class="summary">共 {{ filtered.length }} 条车辆数据</div>
    </el-card>
    <VehicleFormDialog v-if="authStore.canManageMasterData" v-model="dialogVisible" :vehicle="editing" :vehicle-types="vehicleTypes" :drivers="drivers" :submitting="submitting" @submit="submit" />
  </section>
</template>

<style scoped>
.master-page { max-width: 1500px; margin: 0 auto; }.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 22px; }.eyebrow { margin: 0 0 7px !important; color: #2f80ed !important; font-size: 13px; font-weight: 600; }.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }.page-heading p { margin: 9px 0 0; color: #6b778c; }.table-card { border-color: #e4eaf2; border-radius: 14px; }.toolbar,.filters { display: flex; align-items: center; gap: 12px; }.toolbar { justify-content: space-between; margin-bottom: 18px; }.filters .el-input { width: 330px; }.filters .el-select { width: 190px; }.code { margin-top: 4px; color: #8993a4; font-family: Consolas, monospace; font-size: 12px; }.summary { margin-top: 14px; color: #8993a4; font-size: 12px; text-align: right; }
</style>
