<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api/driverLeave'
import { listVehicles } from '@/api/vehicles'
import type { Vehicle } from '@/types/vehicle'
import AutoSubstitutionPanel from './AutoSubstitutionPanel.vue'
import { businessRef } from '@/utils/businessLabels'
const props = defineProps<{ mode?: string }>()
const admin = computed(() => useAuthStore().user?.role === 'ADMIN')
const leaves = ref<api.LeaveRequest[]>([]), substitutions = ref<api.Substitute[]>([])
const loading = ref(false), saving = ref(false), error = ref(''), detail = ref<(api.LeaveRequest & { affected_tasks: api.AffectedTask[] }) | null>(null)
const selected = ref<api.LeaveRequest | null>(null), day = ref(''), period = ref('MORNING')
const manual = ref(false), vehicles = ref<Vehicle[]>([]), vehicleId = ref<number | null>(null)
const vehicleLoading = ref(false)
const targetVehicleId = computed(() => manual.value ? vehicleId.value : selected.value?.vehicle_id)
const recommendations = ref<Awaited<ReturnType<typeof api.getRecommendations>>['data'] | null>(null)
let requestVersion = 0
let recommendationVersion = 0
const message = (e: unknown) => e && typeof e === 'object' && 'message' in e ? String(e.message) : '操作失败，请重试'
async function load() {
  const version = ++requestVersion
  loading.value = true; error.value = ''; leaves.value = []; substitutions.value = []
  try { const [l, s] = await Promise.all([api.getLeaveRequests(), api.getSubstitutions()]); if (version === requestVersion) { leaves.value = l.data; substitutions.value = s.data } }
  catch (e) { if (version === requestVersion) error.value = message(e) }
  finally { if (version === requestVersion) loading.value = false }
}
async function action(fn: () => Promise<unknown>) {
  if (saving.value) return
  saving.value = true; error.value = ''
  try { await fn(); ElMessage.success('操作成功'); recommendations.value = null; await load() }
  catch (e) { error.value = message(e) }
  finally { saving.value = false }
}
async function inspect(row: api.LeaveRequest) {
  try { detail.value = (await api.getLeaveDetail(row.id)).data } catch (e) { error.value = message(e) }
}
async function review(row: api.LeaveRequest, decision: 'APPROVED' | 'REJECTED') {
  try {
    const current = (await api.getLeaveDetail(row.id)).data
    detail.value = current
    const locked = current.affected_tasks.filter(task => task.driver_locked).length
    const result = await ElMessageBox.prompt(`影响 ${current.affected_tasks.length} 个已发布任务，其中 ${locked} 个归属已锁定。审批不会自动交接或改派，请填写审核备注。`, decision === 'APPROVED' ? '确认批准请假' : '驳回请假')
    await action(() => api.reviewLeave(row.id, decision, result.value || ''))
    detail.value = (await api.getLeaveDetail(row.id)).data
  }
  catch (e) { if (e !== 'cancel' && e !== 'close') error.value = message(e) }
}
function clearRecommendations() { recommendationVersion++; recommendations.value = null }
function choose(row: api.LeaveRequest) { manual.value = false; selected.value = row; day.value = row.start_date; period.value = row.period === 'AFTERNOON' ? 'AFTERNOON' : 'MORNING'; clearRecommendations() }
async function openManual() {
  if (!admin.value || vehicleLoading.value) return
  manual.value = true; selected.value = null; vehicleId.value = null; clearRecommendations()
  const now = new Date()
  day.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  period.value = 'MORNING'; vehicleLoading.value = true; error.value = ''; vehicles.value = []
  try {
    const rows: Vehicle[] = []
    for (let offset = 0; ; offset += 100) {
      const batch = (await listVehicles({ offset, limit: 100 })).data
      rows.push(...batch)
      if (batch.length < 100) break
    }
    vehicles.value = rows.filter(v => v.is_active && v.driver_user_id !== null)
  } catch (e) { error.value = message(e) }
  finally { vehicleLoading.value = false }
}
async function recommend() {
  const target = targetVehicleId.value
  if (!target || !day.value) { error.value = '请先选择车辆和调班日期'; return }
  const version = ++recommendationVersion
  recommendations.value = null; loading.value = true; error.value = ''
  try { const result = (await api.getRecommendations(day.value, period.value, target)).data; if (version === recommendationVersion) recommendations.value = result }
  catch (e) { if (version === recommendationVersion) error.value = message(e) } finally { loading.value = false }
}
async function propose(candidate: api.Recommendation) {
  const target = targetVehicleId.value
  if (!admin.value || !target || !day.value) return
  const payload = { ...(manual.value ? {} : { leave_request_id: selected.value!.id }), vehicle_id: target, substitute_driver_id: candidate.driver_id, date: day.value, period: period.value }
  try { await ElMessageBox.confirm(`将 ${candidate.name} 保存为 ${payload.date} ${payload.period} 的待确认代班？保存后，请在下方“临时代班记录”点击“确认调度”才会生效。`, '任命代班司机'); await action(() => api.proposeSubstitution(payload)) }
  catch (e) { if (e !== 'cancel' && e !== 'close') error.value = message(e) }
}
async function change(row: api.Substitute, cancel = false) {
  if (!admin.value) return
  try { await ElMessageBox.confirm(cancel ? '取消后车辆可能不可派车；执行中任务将拒绝取消。' : '确认后才生效；系统将重新校验资格并更新尚未执行任务归属。', cancel ? '取消代班' : '管理员确认代班'); await action(() => cancel ? api.cancelSubstitution(row.id) : api.confirmSubstitution(row.id)) }
  catch (e) { if (e !== 'cancel' && e !== 'close') error.value = message(e) }
}
onMounted(load)
</script>
<template>
  <section class="leave-page">
    <header><div><h1>{{ props.mode === 'substitution' ? '代班调度' : '司机请假审批' }}</h1><p>申请、系统推荐、待确认和已确认生效分开管理，长期绑定不变。</p></div><div><el-button v-if="admin" type="primary" :loading="vehicleLoading" :disabled="saving" @click="openManual">人工任命代班</el-button><el-button :loading="loading" @click="load">刷新</el-button></div></header>
    <el-alert :title="admin ? '代班调度页可自动发现缺岗并推荐司机，直接选择候选并确认调度。人工任命是备用入口；所有操作仅指定日期、班次生效，不修改长期绑定。' : '当前账号为只读调度权限。请使用 ADMIN 管理员账号任命司机和确认调度。'" type="info" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <AutoSubstitutionPanel v-if="props.mode === 'substitution'" @updated="load" />
    <el-card v-loading="loading">
      <el-table :data="leaves" empty-text="暂无请假申请">
        <el-table-column label="申请编号" min-width="190"><template #default="{ row }">{{ businessRef('LV', row.id, row.start_date) }}</template></el-table-column>
        <el-table-column label="员工编号" min-width="100"><template #default="{ row }">{{ businessRef('DRV', row.driver_id) }}</template></el-table-column>
        <el-table-column prop="driver_name" label="司机" /><el-table-column prop="plate_number" label="常驻车辆" />
        <el-table-column label="日期 / 班次" min-width="210"><template #default="{ row }">{{ row.start_date }} ～ {{ row.end_date }}<br>{{ row.period }}</template></el-table-column>
        <el-table-column prop="reason" label="原因（权限脱敏）" /><el-table-column prop="status" label="状态" /><el-table-column prop="review_remark" label="审核备注" /><el-table-column prop="reviewed_at" label="审批时间" min-width="180" />
        <el-table-column label="操作" min-width="240"><template #default="{ row }">
          <el-button link @click="inspect(row)">受影响任务</el-button>
          <template v-if="admin && row.status === 'PENDING'"><el-button link :disabled="saving" @click="review(row, 'APPROVED')">批准</el-button><el-button link type="danger" :disabled="saving" @click="review(row, 'REJECTED')">驳回</el-button></template>
          <el-button v-if="row.status === 'APPROVED' && row.vehicle_id" link @click="choose(row)">选择代班班次</el-button>
        </template></el-table-column>
      </el-table>
    </el-card>
    <el-card v-if="selected || manual">
      <h3>{{ manual ? '人工任命代班司机' : selected?.driver_name + ' · ' + selected?.plate_number }} · 候选查询（不会自动绑定）</h3>
      <div class="controls"><el-select v-if="manual" v-model="vehicleId" placeholder="选择车辆（需已绑定常驻司机）" filterable :loading="vehicleLoading" @change="clearRecommendations"><el-option v-for="vehicle in vehicles" :key="vehicle.id" :label="vehicle.plate_number" :value="vehicle.id" /></el-select><el-date-picker v-model="day" value-format="YYYY-MM-DD" :clearable="false" :disabled="saving" @change="clearRecommendations" /><el-select v-model="period" :disabled="saving" @change="clearRecommendations"><el-option label="上午" value="MORNING" /><el-option label="下午" value="AFTERNOON" /></el-select><el-button :loading="loading" :disabled="saving || !targetVehicleId" @click="recommend">查询候选司机</el-button></div>
      <p v-if="manual && !vehicleLoading && !vehicles.length">没有已绑定常驻司机的启用车辆，请先在司机与排班页面检查绑定。</p>
      <template v-if="recommendations"><el-alert :title="recommendations.qualification_notice" :closable="false" />
        <el-table :data="recommendations.candidates" empty-text="没有符合条件的候选司机"><el-table-column prop="rank" label="推荐顺序" /><el-table-column prop="name" label="司机" /><el-table-column label="依据" min-width="300"><template #default="{ row }">{{ row.reasons.join('；') }}<small>{{ row.validated_constraints.join(' / ') }}</small></template></el-table-column><el-table-column v-if="admin" label="操作"><template #default="{ row }"><el-button :disabled="saving" @click="propose(row)">保存待确认</el-button></template></el-table-column></el-table>
        <el-collapse><el-collapse-item title="不可推荐司机及原因"><el-table :data="recommendations.rejected"><el-table-column prop="name" label="司机" /><el-table-column prop="reason" label="原因" /></el-table></el-collapse-item></el-collapse>
      </template>
    </el-card>
    <el-card><h3>临时代班记录</h3><p>只有待确认（PENDING）记录显示“确认调度”；CONFIRMED 已生效，无需重复确认。</p><el-table :data="substitutions" empty-text="暂无代班记录"><el-table-column prop="date" label="日期" /><el-table-column prop="period" label="班次" /><el-table-column prop="plate_number" label="车辆" /><el-table-column prop="original_driver_name" label="常驻司机" /><el-table-column prop="substitute_driver_name" label="代班司机" /><el-table-column prop="status" label="状态" /><el-table-column prop="confirmed_at" label="确认时间" min-width="180" /><el-table-column v-if="admin" label="操作" fixed="right" min-width="190"><template #default="{ row }"><el-button v-if="row.status === 'PENDING'" :disabled="saving" type="primary" @click="change(row)">确认调度</el-button><el-button v-if="row.status !== 'CANCELLED'" :disabled="saving" link type="danger" @click="change(row, true)">取消</el-button></template></el-table-column></el-table></el-card>
    <el-dialog :model-value="!!detail" title="请假与任务冲突" width="min(900px, 95vw)" @close="detail = null"><template v-if="detail"><p>申请 #{{ detail.id }} · {{ detail.status }}。审批不改派已执行任务。</p><el-table :data="detail.affected_tasks" empty-text="没有受影响的已发布任务"><el-table-column prop="task_id" label="任务" /><el-table-column prop="plan_id" label="方案" /><el-table-column prop="date" label="日期" /><el-table-column prop="period" label="班次" /><el-table-column label="状态"><template #default="{ row }">{{ row.statuses.join(' / ') }}{{ row.driver_locked ? '（归属锁定）' : '（需重校验）' }}</template></el-table-column></el-table></template></el-dialog>
  </section>
</template>
<style scoped>
.leave-page { display: grid; gap: 20px; } header,.controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; } h1 { margin: 0; } p,small { color: #76879d; } small { display: block; margin-top: 8px; } .controls { justify-content: flex-start; margin-bottom: 16px; }
</style>
