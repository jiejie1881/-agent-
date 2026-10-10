<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api/driverScheduling'
import { businessRef } from '@/utils/businessLabels'
import { fetchEnterpriseOverview, type EnterpriseOverview } from '@/api/enterprise'

const auth = useAuthStore()
const admin = computed(() => auth.user?.role === 'ADMIN')
const writable = computed(() => ['ADMIN', 'DISPATCHER'].includes(auth.user?.role || ''))
const day = ref(new Date().toLocaleDateString('sv-SE'))
const loading = ref(false), saving = ref(false), error = ref('')
const drivers = ref<api.DriverRow[]>([]), shifts = ref<api.ShiftRow[]>([]), leaves = ref<api.LeaveRow[]>([])
const enterprise = ref<EnterpriseOverview | null>(null), keyword = ref(''), identityError = ref('')
const identity = (id: number) => enterprise.value?.drivers.find(d => d.id === id)
const visibleDrivers = computed(() => drivers.value.filter(d => (!driverFilter.value || d.id === driverFilter.value) && `${d.display_name ?? ''} ${d.username} ${businessRef('DRV',d.id)} ${d.default_plate ?? ''}`.toLowerCase().includes(keyword.value.trim().toLowerCase())))
const driverFilter = ref<number | null>(null), vehicleFilter = ref<number | null>(null)
const dialog = ref(''), target = ref<api.DriverRow | null>(null), selectedShift = ref<api.ShiftRow | null>(null)
const username = ref(''), name = ref(''), password = ref(''), chosenDriver = ref<number | null>(null), chosenVehicle = ref<number | null>(null)
const candidates = ref<api.Candidate[]>([])
const attendanceEdit = ref({ driver_id: 0, username: '', date: '', period: 'MORNING', available: false, scope: 'ONCE' })
const leave = ref({ driver_id: 0, start_date: '', end_date: '', period: 'ALL_DAY', reason: '', remark: '' })
const visibleShifts = computed(() => shifts.value.filter(s => (!driverFilter.value || s.driver_id === driverFilter.value || s.default_driver_id === driverFilter.value) && (!vehicleFilter.value || s.vehicle_id === vehicleFilter.value)))
const vehicles = computed(() => [...new Map(shifts.value.map(s => [s.vehicle_id, { id: s.vehicle_id, plate: s.plate_number }])).values()])
const driverLabel = (id: number | null) => { const d = drivers.value.find(d => d.id === id); return d ? `${d.display_name || '姓名未填写'} · ${businessRef('DRV',id)}` : '未绑定' }
let requestVersion = 0
function errorMessage(e: unknown, fallback: string) {
  // Axios 统一封装拒绝的是 ApiError 对象，不一定是 Error 实例。
  return e && typeof e === 'object' && 'message' in e && typeof e.message === 'string' && e.message
    ? e.message : fallback
}
async function load() {
  const version = ++requestVersion
  const date = day.value
  loading.value = true; error.value = ''
  enterprise.value = null; identityError.value = ''
  drivers.value = []; shifts.value = []; leaves.value = []
  try {
    const [d, s, l] = await Promise.all([api.fetchDrivers(date), api.fetchShifts(date), api.fetchLeaves()])
    if (version !== requestVersion) return
    drivers.value = d.data; shifts.value = s.data; leaves.value = l.data
    try { const result = (await fetchEnterpriseOverview(date)).data; if (version === requestVersion) enterprise.value = result } catch { if (version === requestVersion) identityError.value = '司机运营身份加载失败，请刷新重试；已有排班功能不受影响。' }
  } catch (e) { if (version === requestVersion) error.value = errorMessage(e, '加载失败') }
  finally { if (version === requestVersion) loading.value = false }
}
async function action(fn: () => Promise<unknown>) {
  if (saving.value) return
  saving.value = true
  try { await fn(); ElMessage.success('操作成功'); dialog.value = ''; await load() }
  catch (e) { error.value = errorMessage(e, '操作失败') }
  finally { saving.value = false }
}
function openDriver(kind: string, driver: api.DriverRow | null = null) {
  target.value = driver; username.value = driver?.username || ''; name.value = driver?.display_name || ''; password.value = ''; chosenVehicle.value = driver?.default_vehicle_id || null; dialog.value = kind
}
function openAttendance(driver: api.DriverRow, period: string, available: boolean) {
  attendanceEdit.value = { driver_id: driver.id, username: driver.display_name || driver.username, date: day.value, period, available, scope: 'ONCE' }
  dialog.value = 'attendance'
}
async function openShift(s: api.ShiftRow) {
  selectedShift.value = s; chosenDriver.value = null
  if (s.schedule_id) {
    try { candidates.value = (await api.fetchCandidates(s.schedule_id)).data; dialog.value = 'substitute' }
    catch (e) { error.value = errorMessage(e, '候选司机加载失败') }
  } else { dialog.value = 'assign' }
}
function save() {
  if (dialog.value === 'attendance') {
    const edit = { ...attendanceEdit.value }
    void action(() => edit.scope === 'PERMANENT'
      ? api.setFixedDriverAttendance(edit.driver_id, edit.date, edit.period, edit.available)
      : api.setDriverAttendance(edit.driver_id, edit.date, edit.period, edit.available))
  } else if (dialog.value === 'create') {
    if (!username.value.trim() || password.value.length < 8) { ElMessage.warning('账号必填，密码至少8位'); return }
    void action(() => api.createDriver({ username: username.value.trim(), display_name: name.value, password: password.value }))
  } else if (dialog.value === 'edit' && target.value) { const id = target.value.id; void action(() => api.updateDriver(id, { display_name: name.value })) }
  else if (dialog.value === 'password' && target.value) {
    if (password.value.length < 8) { ElMessage.warning('密码至少8位'); return }
    const id = target.value.id; void action(() => api.resetDriverPassword(id, password.value))
  } else if (dialog.value === 'binding' && target.value) { const id = target.value.id; void action(() => api.bindDefaultVehicle(id, chosenVehicle.value)) }
  else if (dialog.value === 'leave') {
    if (!leave.value.driver_id || !leave.value.reason.trim() || !leave.value.start_date || !leave.value.end_date) { ElMessage.warning('请填写司机、日期与原因'); return }
    void action(() => api.createDriverLeave({ ...leave.value, remark: leave.value.remark || null }))
  } else if (selectedShift.value && chosenDriver.value) {
    const s = selectedShift.value, id = chosenDriver.value
    void action(() => s.schedule_id ? api.substituteDriver(s.schedule_id, id) : api.assignShift(day.value, s.period, s.vehicle_id, id))
  } else { ElMessage.warning('请选择司机') }
}
async function toggle(driver: api.DriverRow) {
  try { await ElMessageBox.confirm(`确认${driver.is_active ? '停用' : '启用'} ${driver.username}？`, '账号状态'); await action(() => api.updateDriver(driver.id, { is_active: !driver.is_active })) } catch { /* 取消不改变状态 */ }
}
onMounted(load)
</script>

<template>
  <section class="driver-page">
    <header><div><h1>司机与排班工作台</h1><p>默认车辆与实际班次分开管理。配送中、已完成任务禁止普通代班。</p></div><el-button @click="load" :loading="loading">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-alert v-if="identityError" :title="identityError" type="warning" :closable="false" />
    <el-input v-model="keyword" clearable placeholder="搜索司机姓名、账号、工号或常驻车牌" />
    <div class="filters"><el-date-picker v-model="day" value-format="YYYY-MM-DD" :clearable="false" @change="load" /><el-select v-model="driverFilter" clearable placeholder="司机筛选"><el-option v-for="d in drivers" :key="d.id" :value="d.id" :label="d.display_name || d.username" /></el-select><el-select v-model="vehicleFilter" clearable placeholder="车辆筛选"><el-option v-for="v in vehicles" :key="v.id" :value="v.id" :label="v.plate" /></el-select></div>
    <el-tabs v-loading="loading">
      <el-tab-pane label="司机管理与出勤">
        <el-alert title="每位司机有固定的上午/下午出勤。点击开关可选择仅当天或永久修改；永久修改从所选日期生效，其他日期的临时调整仍优先。请假与排班冲突仍由后端校验。" type="info" :closable="false" />
        <el-button v-if="admin" type="primary" @click="openDriver('create')">创建司机</el-button>
        <el-table :data="visibleDrivers" empty-text="暂无司机">
          <el-table-column label="工号" min-width="120"><template #default="{row}">{{ businessRef('DRV',row.id) }}</template></el-table-column>
          <el-table-column v-if="writable" prop="username" label="登录账号" min-width="150" /><el-table-column label="姓名" min-width="120"><template #default="{row}">{{ row.display_name || '姓名未填写' }}</template></el-table-column><el-table-column prop="default_plate" label="常驻车辆" min-width="130" /><el-table-column prop="today_task_count" label="当日任务" />
          <el-table-column label="当前有效车辆" min-width="200"><template #default="{row}"><div v-for="v in identity(row.id)?.effective_vehicles" :key="v.code+v.period">{{ v.period === 'MORNING' ? '上午' : '下午' }}：{{ v.plate_number }} · {{ v.code }}</div><span v-if="!identity(row.id)?.effective_vehicles.length">{{ identity(row.id) ? '无有效排班车辆' : '资料未加载' }}</span></template></el-table-column>
          <el-table-column label="请假 / 代班" min-width="180"><template #default="{row}"><div v-for="l in identity(row.id)?.leaves" :key="l.code">{{ l.code }} · {{ l.status }} · {{ l.period }}</div><div v-for="(s,i) in identity(row.id)?.substitutions" :key="i">{{ s.as_substitute ? '担任代班' : '常驻车代班' }} · {{ s.status }}</div><span v-if="!identity(row.id)?.leaves.length && !identity(row.id)?.substitutions.length">{{ identity(row.id) ? '无记录' : '资料未加载' }}</span></template></el-table-column>
          <el-table-column label="启用"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag></template></el-table-column>
          <el-table-column v-for="p in ['MORNING', 'AFTERNOON']" :key="p" :label="p === 'MORNING' ? '上午出勤' : '下午出勤'" min-width="150"><template #default="{ row }"><el-switch :model-value="row.attendance[p]" :disabled="!writable || saving || loading" @change="(value: boolean | string | number) => openAttendance(row, p, !!value)" /><small>固定：{{ row.attendance_details?.[p]?.fixed_available === null || row.attendance_details?.[p]?.fixed_available === undefined ? '未设置' : row.attendance_details[p].fixed_available ? '出勤' : '休息' }}</small><el-tag size="small" :type="row.attendance_details?.[p]?.source === 'ONCE' ? 'warning' : 'info'">{{ row.attendance_details?.[p]?.source === 'ONCE' ? '当天调整' : row.attendance_details?.[p]?.source === 'FIXED' ? '固定班次' : '未设置' }}</el-tag><el-button v-if="writable" link size="small" :disabled="saving || loading" @click="openAttendance(row, p, row.attendance[p])">修改</el-button></template></el-table-column>
          <el-table-column v-if="admin" label="操作" width="300"><template #default="{ row }"><el-button link @click="openDriver('edit', row)">编辑</el-button><el-button link @click="openDriver('binding', row)">默认车辆</el-button><el-button link @click="openDriver('password', row)">重置密码</el-button><el-button link @click="toggle(row)">{{ row.is_active ? '停用' : '启用' }}</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="实际排班与代班">
        <el-alert title="先登记车辆出勤与司机班次出勤，再安排实际司机。没有司机的车辆不可自动派车。" type="info" :closable="false" />
        <el-table :data="visibleShifts" empty-text="暂无车辆">
          <el-table-column prop="plate_number" label="车辆" /><el-table-column label="班次"><template #default="{ row }">{{ row.period === 'MORNING' ? '上午' : '下午' }}</template></el-table-column>
          <el-table-column label="默认司机"><template #default="{ row }">{{ driverLabel(row.default_driver_id) }}</template></el-table-column><el-table-column prop="driver_name" label="实际司机" />
          <el-table-column label="类型"><template #default="{ row }">{{ row.kind === 'SUBSTITUTE' ? '临时代班' : row.kind ? '正常排班' : '未安排' }}</template></el-table-column><el-table-column prop="conflict" label="冲突 / 未解决原因" min-width="220" />
          <el-table-column v-if="writable" label="操作"><template #default="{ row }"><el-button v-if="!row.schedule_id" link type="primary" :disabled="saving" @click="openShift(row)">排班</el-button><router-link v-else to="/operations/substitutions">查看代班调度</router-link></template></el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="请假与历史">
        <router-link to="/operations/leave-approval">请假审批与受影响任务</router-link>
        <el-button v-if="admin" type="primary" @click="leave = { driver_id: 0, start_date: day, end_date: day, period: 'ALL_DAY', reason: '', remark: '' }; dialog = 'leave'">代录待审批申请</el-button>
        <el-table :data="leaves" empty-text="暂无请假记录"><el-table-column label="司机"><template #default="{ row }">{{ driverLabel(row.driver_id) }}</template></el-table-column><el-table-column prop="start_date" label="开始" /><el-table-column prop="end_date" label="结束" /><el-table-column prop="period" label="班次" /><el-table-column prop="reason" label="原因" /><el-table-column prop="status" label="状态" /><el-table-column v-if="admin" label="操作"><template #default="{ row }"><el-button v-if="row.status === 'PENDING'" link :disabled="saving" @click="action(() => api.cancelDriverLeave(row.id))">撤回申请</el-button></template></el-table-column></el-table>
      </el-tab-pane>
    </el-tabs>
    <el-dialog :model-value="!!dialog" title="司机业务操作" width="520px" @close="dialog = ''; password = ''">
      <el-form label-width="110px">
        <template v-if="dialog === 'attendance'">
          <el-form-item label="司机">{{ attendanceEdit.username }}</el-form-item>
          <el-form-item label="业务日期">{{ attendanceEdit.date }}</el-form-item>
          <el-form-item label="班次">{{ attendanceEdit.period === 'MORNING' ? '上午' : '下午' }}</el-form-item>
          <el-form-item label="出勤状态"><el-switch v-model="attendanceEdit.available" active-text="出勤" inactive-text="休息" /></el-form-item>
          <el-form-item label="修改范围"><el-radio-group v-model="attendanceEdit.scope"><el-radio value="ONCE">仅当天</el-radio><el-radio value="PERMANENT">永久修改</el-radio></el-radio-group></el-form-item>
          <el-alert :title="attendanceEdit.scope === 'ONCE' ? '只调整这个日期，不改变固定班次。' : '从该日期起每天采用此固定设置；替换当天临时设置，其他日期已有临时调整保留。'" type="info" :closable="false" />
        </template>
        <template v-if="['create', 'edit', 'password'].includes(dialog)"><el-form-item v-if="dialog === 'create'" label="登录账号"><el-input v-model="username" /></el-form-item><el-form-item v-if="dialog !== 'password'" label="司机姓名"><el-input v-model="name" /></el-form-item><el-form-item v-if="dialog !== 'edit'" label="初始密码"><el-input v-model="password" type="password" show-password /><small>至少8位，请安全发放，不公开导出。</small></el-form-item></template>
        <el-form-item v-if="dialog === 'binding'" label="默认车辆"><el-select v-model="chosenVehicle" clearable placeholder="不绑定"><el-option v-for="v in vehicles" :key="v.id" :label="v.plate" :value="v.id" /></el-select></el-form-item>
        <el-form-item v-if="['assign', 'substitute'].includes(dialog)" label="实际司机"><el-select v-model="chosenDriver"><template v-if="dialog === 'substitute'"><el-option v-for="c in candidates" :key="c.id" :value="c.id" :disabled="!!c.reason" :label="(c.display_name || c.username) + (c.reason ? '：' + c.reason : '')" /></template><template v-else><el-option v-for="d in drivers" :key="d.id" :value="d.id" :disabled="!d.is_active" :label="d.display_name || d.username" /></template></el-select><small>最终可用性由后端校验。</small></el-form-item>
        <template v-if="dialog === 'leave'"><el-form-item label="司机"><el-select v-model="leave.driver_id"><el-option v-for="d in drivers" :key="d.id" :value="d.id" :label="d.display_name || d.username" /></el-select></el-form-item><el-form-item label="开始日期"><el-date-picker v-model="leave.start_date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="结束日期"><el-date-picker v-model="leave.end_date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="班次"><el-select v-model="leave.period"><el-option label="全天" value="ALL_DAY" /><el-option label="上午" value="MORNING" /><el-option label="下午" value="AFTERNOON" /></el-select></el-form-item><el-form-item label="请假原因"><el-input v-model="leave.reason" /></el-form-item><el-form-item label="备注"><el-input v-model="leave.remark" /></el-form-item></template>
      </el-form>
      <template #footer><el-button @click="dialog = ''">取消</el-button><el-button type="primary" :loading="saving" @click="save">确认</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.driver-page { padding: 24px; background: white; border-radius: 16px; }
header { display: flex; justify-content: space-between; align-items: center; } h1 { margin: 0; } p, small { color: #7b8794; }
.filters { display: flex; gap: 16px; margin: 24px 0; flex-wrap: wrap; } .filters .el-select { width: 200px; }
.el-alert { margin: 16px 0; } small { display: block; }
</style>
