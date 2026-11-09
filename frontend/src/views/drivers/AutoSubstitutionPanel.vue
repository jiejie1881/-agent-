<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { loadSubstitutionOverview, confirmRecommendedSubstitution, type SubstitutionGap } from '@/api/substitutionOverview'
const emit = defineEmits<{ updated: [] }>()
const admin = computed(() => useAuthStore().user?.role === 'ADMIN')
const now = new Date()
const date = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`)
const rows = ref<SubstitutionGap[]>([]), loading = ref(false), saving = ref(false), error = ref('')
let generation = 0
const message = (e: unknown) => e && typeof e === 'object' && 'message' in e ? String(e.message) : '操作失败，请重试'
async function refresh() {
  const current = ++generation
  rows.value = []; error.value = ''; loading.value = true
  try { const result = await loadSubstitutionOverview(date.value); if (current === generation) rows.value = result }
  catch (e) { if (current === generation) error.value = message(e) }
  finally { if (current === generation) loading.value = false }
}
async function confirm(row: SubstitutionGap) {
  if (!admin.value || saving.value || row.blocked || row.error || !row.selectedDriverId) return
  const driverId = row.selectedDriverId
  const candidate = row.candidates.find(c => c.driver_id === driverId)
  if (!candidate) return
  saving.value = true
  try {
    await ElMessageBox.confirm(`确认由 ${candidate.name} 驾驶 ${row.plate_number}，代班日期 ${row.date}，${row.period === 'MORNING' ? '上午' : '下午'}？系统将重新校验，长期绑定不变。`, '确认调度', { confirmButtonText: '确认调度', cancelButtonText: '取消' })
    await confirmRecommendedSubstitution(row, driverId)
    ElMessage.success('代班调度已确认生效')
    emit('updated')
    await refresh()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      row.error = message(e) + '。如已保存待确认记录，可在下方记录中继续处理；请刷新候选后重试。'
      if (row.pending.length) emit('updated')
    }
  } finally { saving.value = false }
}
onMounted(refresh)
onBeforeUnmount(() => { generation++ })
defineExpose({ refresh })
</script>
<template>
  <el-card class="auto-substitution">
    <div class="heading"><div><h2>自动代班推荐</h2><p>选择日期，系统自动发现上午、下午缺岗并推荐候选司机。管理员选人确认后才生效。</p></div><div class="filters"><el-date-picker v-model="date" value-format="YYYY-MM-DD" :clearable="false" :disabled="saving" @change="refresh" /><el-button :loading="loading" :disabled="saving" @click="refresh">刷新推荐</el-button></div></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-loading="loading">
      <el-empty v-if="!loading && !error && !rows.length" description="该日期没有发现出勤车辆的司机缺岗；请核对业务日期和车辆出勤" />
      <div v-for="row in rows" :key="row.key" class="gap">
        <div class="gap-title"><strong>{{ row.plate_number }} · {{ row.period === 'MORNING' ? '上午' : '下午' }}</strong><el-tag type="warning">{{ row.reason }}</el-tag></div>
        <el-alert v-if="row.blocked || row.error" :title="row.blocked || row.error" :type="row.error ? 'error' : 'warning'" :closable="false" />
        <template v-else>
          <p v-if="!row.candidates.length">没有合适候选司机，不能强行调度。</p>
          <div v-else class="filters"><el-select v-model="row.selectedDriverId" :disabled="saving || !admin" placeholder="选择推荐司机" class="candidate"><el-option v-for="candidate in row.candidates" :key="candidate.driver_id" :value="candidate.driver_id" :label="`推荐 ${candidate.rank}：${candidate.name}（当天 ${candidate.daily_task_count} 趟）`" /></el-select><el-button v-if="admin" type="primary" :disabled="saving || !row.selectedDriverId" @click="confirm(row)">确认调度</el-button><span v-else>仅 ADMIN 管理员可确认</span></div>
          <p v-for="candidate in row.candidates.filter(c => c.driver_id === row.selectedDriverId)" :key="candidate.driver_id">推荐依据：{{ candidate.reasons.join('；') }}<br>已检查：{{ candidate.validated_constraints.join(' / ') }}</p>
          <p>{{ row.qualification_notice }}</p>
          <el-collapse v-if="row.rejected.length"><el-collapse-item title="查看不可推荐司机及原因"><el-table :data="row.rejected"><el-table-column prop="name" label="司机" /><el-table-column prop="reason" label="原因" /></el-table></el-collapse-item></el-collapse>
        </template>
      </div>
    </div>
  </el-card>
</template>
<style scoped>
h2 { margin: 0; } p { color: #76879d; line-height: 1.7; } .heading,.filters,.gap-title { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; } .heading { justify-content: space-between; } .gap { border-top: 1px solid #eef1f5; margin-top: 20px; padding-top: 20px; } .gap-title { margin-bottom: 16px; } .candidate { width: 360px; max-width: 100%; } .filters { margin: 12px 0; }
</style>
