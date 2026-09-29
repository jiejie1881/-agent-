<script setup lang="ts">
import { Calendar, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import {
  createVehicleAttendance,
  listVehicleAttendances,
  listVehicles,
  updateVehicleAttendance,
} from '@/api/vehicles'
import type { VehicleAttendanceRow } from '@/types/vehicle'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

function localDate(): string {
  const value = new Date()
  return [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, '0'),
    String(value.getDate()).padStart(2, '0'),
  ].join('-')
}

const selectedDate = ref(localDate())
const selectedVehicleTypeId = ref<number | null>(null)
const loading = ref(false)
const updatingVehicleIds = ref(new Set<number>())
const rows = ref<VehicleAttendanceRow[]>([])

const vehicleTypeOptions = computed(() => {
  const map = new Map<number, { id: number; name: string; code: string }>()
  rows.value.forEach(({ vehicle }) => {
    map.set(vehicle.vehicle_type.id, {
      id: vehicle.vehicle_type.id,
      name: vehicle.vehicle_type.name,
      code: vehicle.vehicle_type.code,
    })
  })
  return [...map.values()].sort((left, right) => left.id - right.id)
})

const filteredRows = computed(() => {
  if (!selectedVehicleTypeId.value) return rows.value
  return rows.value.filter(
    ({ vehicle }) => vehicle.vehicle_type_id === selectedVehicleTypeId.value,
  )
})

const summary = computed(() => ({
  total: filteredRows.value.length,
  available: filteredRows.value.filter((row) => row.available === true).length,
  unavailable: filteredRows.value.filter((row) => row.available === false).length,
  unset: filteredRows.value.filter((row) => row.available === null).length,
}))

async function loadData() {
  loading.value = true
  try {
    const [vehicleResponse, attendanceResponse] = await Promise.all([
      listVehicles({ offset: 0, limit: 100 }),
      listVehicleAttendances({ date: selectedDate.value, offset: 0, limit: 100 }),
    ])
    const attendanceByVehicle = new Map(
      attendanceResponse.data.map((attendance) => [attendance.vehicle_id, attendance]),
    )
    rows.value = vehicleResponse.data.map((vehicle) => {
      const attendance = attendanceByVehicle.get(vehicle.id)
      return {
        vehicle,
        attendanceId: attendance?.id ?? null,
        available: attendance?.available ?? null,
      }
    })
  } catch {
    // Axios interceptor displays backend errors.
  } finally {
    loading.value = false
  }
}

async function setAvailability(row: VehicleAttendanceRow, available: boolean) {
  if (row.available === available && row.attendanceId !== null) return
  updatingVehicleIds.value.add(row.vehicle.id)
  try {
    const response = row.attendanceId
      ? await updateVehicleAttendance(row.attendanceId, { available })
      : await createVehicleAttendance({
          date: selectedDate.value,
          vehicle_id: row.vehicle.id,
          available,
        })
    row.attendanceId = response.data.id
    row.available = response.data.available
    ElMessage.success(`${row.vehicle.plate_number} 已设为${available ? '可出勤' : '不可出勤'}`)
  } catch {
    // Axios interceptor displays backend errors; keep the previous row state.
  } finally {
    updatingVehicleIds.value.delete(row.vehicle.id)
  }
}

onMounted(loadData)
</script>

<template>
  <section class="operation-page">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">每日运营</p>
        <h1>车辆出勤</h1>
        <p>按日期登记车辆是否参与当天派车。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
    </div>

    <el-card class="filter-card" shadow="never">
      <div class="filter-row">
        <div class="filter-item">
          <span>运营日期</span>
          <el-date-picker
            v-model="selectedDate"
            type="date"
            value-format="YYYY-MM-DD"
            :prefix-icon="Calendar"
            :clearable="false"
            @change="loadData"
          />
        </div>
        <div class="filter-item">
          <span>车型筛选</span>
          <el-select v-model="selectedVehicleTypeId" clearable placeholder="全部车型" style="width: 200px">
            <el-option
              v-for="item in vehicleTypeOptions"
              :key="item.id"
              :label="`${item.name}（${item.code}）`"
              :value="item.id"
            />
          </el-select>
        </div>
      </div>
    </el-card>

    <div class="summary-grid">
      <div class="summary-item"><span>车辆总数</span><strong>{{ summary.total }}</strong></div>
      <div class="summary-item is-success"><span>可出勤</span><strong>{{ summary.available }}</strong></div>
      <div class="summary-item is-danger"><span>不可出勤</span><strong>{{ summary.unavailable }}</strong></div>
      <div class="summary-item is-muted"><span>未登记</span><strong>{{ summary.unset }}</strong></div>
    </div>

    <el-card class="table-card" shadow="never">
      <el-table v-loading="loading" :data="filteredRows" row-key="vehicle.id" stripe>
        <template #empty><el-empty description="当天暂无车辆数据" :image-size="92" /></template>
        <el-table-column prop="vehicle.plate_number" label="车牌号" min-width="150">
          <template #default="{ row }"><strong>{{ row.vehicle.plate_number }}</strong></template>
        </el-table-column>
        <el-table-column prop="vehicle.code" label="车辆编码" min-width="140" />
        <el-table-column label="车型" min-width="170">
          <template #default="{ row }">
            <div>{{ row.vehicle.vehicle_type.name }}</div>
            <div class="secondary-text">{{ row.vehicle.vehicle_type.code }}</div>
          </template>
        </el-table-column>
        <el-table-column label="车辆状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="row.vehicle.is_active ? 'success' : 'info'">
              {{ row.vehicle.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="出勤登记" width="130" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.available === true" type="success">可出勤</el-tag>
            <el-tag v-else-if="row.available === false" type="danger">不可出勤</el-tag>
            <el-tag v-else type="info">未登记</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="authStore.canOperate" label="设置" width="230" align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="success"
              :plain="row.available !== true"
              :loading="updatingVehicleIds.has(row.vehicle.id)"
              @click="setAvailability(row, true)"
            >可出勤</el-button>
            <el-button
              size="small"
              type="danger"
              :plain="row.available !== false"
              :loading="updatingVehicleIds.has(row.vehicle.id)"
              @click="setAvailability(row, false)"
            >不可出勤</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>

<style scoped>
.operation-page { max-width: 1500px; margin: 0 auto; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
.page-heading__eyebrow { margin: 0 0 7px; color: #2f80ed; font-size: 13px; font-weight: 600; }
.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }
.page-heading p:not(.page-heading__eyebrow) { margin: 9px 0 0; color: #6b778c; }
.filter-card, .table-card { border-color: #e4eaf2; border-radius: 14px; }
.filter-row { display: flex; align-items: center; gap: 28px; }
.filter-item { display: flex; align-items: center; gap: 10px; color: #52627a; font-size: 14px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 16px 0; }
.summary-item { padding: 17px 20px; background: #fff; border: 1px solid #e4eaf2; border-radius: 12px; }
.summary-item span { color: #7a869a; font-size: 13px; }
.summary-item strong { display: block; margin-top: 5px; color: #172b4d; font-size: 25px; }
.summary-item.is-success strong { color: #22a06b; }
.summary-item.is-danger strong { color: #d64545; }
.summary-item.is-muted strong { color: #8993a4; }
.secondary-text { margin-top: 3px; color: #8993a4; font-size: 12px; }
</style>
