<script setup lang="ts">
import { computed } from 'vue'
import { Tickets, Box, Van, Connection, CircleCheck, Warning, Refresh } from '@element-plus/icons-vue'
import { useDashboard } from './useDashboard'
import { demandMetrics, fleetMetrics } from './metrics'
import DashboardPanel from './components/DashboardPanel.vue'
import DashboardStatCard from './components/DashboardStatCard.vue'
import DeliveryStatusChart from './components/DeliveryStatusChart.vue'
import VehicleOverviewChart from './components/VehicleOverviewChart.vue'
import CurrentDispatchPlan from './components/CurrentDispatchPlan.vue'
import DashboardExceptionPanel from './components/DashboardExceptionPanel.vue'
import DashboardQuickActions from './components/DashboardQuickActions.vue'

const { date, demands, fleet, plan, exceptions, updatedAt, load } = useDashboard()
const busy = computed(() => [demands, fleet, plan, exceptions].some(r => r.loading.value))
const metrics = computed(() => demandMetrics(demands.data.value ?? [], plan.data.value))
const vehicles = computed(() => fleetMetrics(fleet.data.value?.vehicles ?? [], fleet.data.value?.attendances ?? [], plan.data.value))
const allocationError = computed(() => demands.error.value || plan.error.value)

const planCounts = computed(() => ({
  assigned: new Set(plan.data.value?.orders.flatMap(o => o.details.map(d => d.delivery_demand_id))).size,
  unassigned: new Set(plan.data.value?.unassigned_demands.map(d => d.delivery_demand_id)).size,
}))
const formattedQuantity = computed(() => metrics.value.quantity.toLocaleString('zh-CN', { maximumFractionDigits: 2 }))
const mapPlanId = computed(() => plan.data.value?.orders.some(o => o.details.some(d => d.store_latitude && d.store_longitude)) ? plan.data.value.id : undefined)
</script>
<template>
  <section class="dashboard">
    <div class="heading"><div><p class="eyebrow">OPERATIONS OVERVIEW</p><h1>运营总览</h1><p class="intro">掌握每日运力、配送进度与异常，连接调度到执行。</p></div><div class="tools"><el-date-picker v-model="date" type="date" value-format="YYYY-MM-DD" :clearable="false" aria-label="业务日期" @change="load" /><el-button :icon="Refresh" :loading="busy" @click="load">刷新</el-button></div></div>
    <div class="context"><span><i />业务日期 {{ date }} · 当前数据快照</span><span>{{ updatedAt ? `最后刷新 ${updatedAt}` : '正在读取业务数据' }}</span></div>
    <div class="stats">
      <DashboardStatCard title="当日配送需求" :value="String(metrics.valid.length)" unit="条" :icon="Tickets" :loading="demands.loading.value" :error="demands.error.value" :description="`有效需求，不含 ${metrics.cancelled} 条已取消需求`" />
      <DashboardStatCard title="当日配送总货量" :value="formattedQuantity" unit="货量单位" :icon="Box" :loading="demands.loading.value" :error="demands.error.value" description="有效需求 quantity 合计；系统未定义 kg/件" tone="#8b5cf6" />
      <DashboardStatCard title="当日出勤 / 车辆总数" :value="`${vehicles.present} / ${vehicles.total}`" unit="辆" :icon="Van" :loading="fleet.loading.value" :error="fleet.error.value" description="明确登记可出勤 / 全部已录入车辆" tone="#0891b2" />
      <DashboardStatCard title="需求分配率" :value="`${metrics.allocationRate.toFixed(1)}%`" :icon="Connection" :loading="demands.loading.value || plan.loading.value" :error="allocationError" :description="plan.data.value ? `当前${plan.data.value.status === 'DRAFT' ? '草稿' : '已发布'}方案去重已分配 / 有效需求` : '暂无参考方案；零需求时显示 0%'" />
      <DashboardStatCard title="配送完成率" :value="`${metrics.completionRate.toFixed(1)}%`" :icon="CircleCheck" :loading="demands.loading.value" :error="demands.error.value" description="COMPLETED / 有效需求，不使用停靠点签收状态" tone="#10b981" />
      <DashboardStatCard title="当日异常总数" value="暂未接入" :icon="Warning" description="接口未提供跨维度去重总数；见下方四类明细" tone="#f59e0b" />
    </div>
    <div class="grid">
      <DashboardPanel title="配送状态分布" subtitle="有效配送需求的当前状态，不含已取消需求" :loading="demands.loading.value" :error="demands.error.value"><DeliveryStatusChart v-if="demands.data.value" :items="metrics.statuses" /></DashboardPanel>
      <DashboardPanel title="车辆运营概况" subtitle="按实际车型配置统计出勤与当前方案任务" :loading="fleet.loading.value" :error="fleet.error.value"><VehicleOverviewChart v-if="fleet.data.value" :overview="vehicles" :plan-ready="!!plan.data.value && !plan.loading.value && !plan.error.value" /></DashboardPanel>
      <DashboardPanel title="当前派车方案" subtitle="优先已发布方案，其次最新草稿；排除取消版本" :loading="plan.loading.value" :error="plan.error.value"><CurrentDispatchPlan v-if="!plan.loading.value" :plan="plan.data.value" :assigned="planCounts.assigned" :unassigned="planCounts.unassigned" /></DashboardPanel>
      <DashboardPanel title="每日异常概况" subtitle="复用每日异常工作台的真实统计口径" :loading="exceptions.loading.value" :error="exceptions.error.value"><template #action><RouterLink to="/dispatch/exceptions" class="text-link">查看全部 →</RouterLink></template><DashboardExceptionPanel v-if="exceptions.data.value" :report="exceptions.data.value" /></DashboardPanel>
      <DashboardPanel title="常用功能" subtitle="根据当前角色提供业务入口"><DashboardQuickActions :plan-id="mapPlanId" /><p class="permission-note">只读账号提供查询入口；业务操作仍由后端校验权限。</p></DashboardPanel>
    </div>
    <p class="snapshot-note">展示所选日期当前业务记录，不是历史时点快照。数据可能来自 Demo 初始化，请以实际记录为准。</p>
  </section>
</template>
<style scoped>
.dashboard { max-width:1600px; margin:0 auto; } .heading { display:flex; align-items:center; justify-content:space-between; gap:24px; margin-bottom:22px; } .eyebrow { color:#2f80ed; font-size:10px; letter-spacing:2px; font-weight:700; margin:0 0 9px; } h1 { color:#172b4d; font-size:30px; letter-spacing:-1px; margin:0; } .intro { color:#7a869a; font-size:13px; line-height:1.7; margin:10px 0 0; } .tools { display:flex; align-items:center; flex-wrap:wrap; gap:10px; } .tools :deep(.el-date-editor) { width:160px; } .context { display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:11px; color:#8592a6; margin-bottom:18px; } .context i { display:inline-block; width:6px; height:6px; background:#10b981; border-radius:50%; margin-right:7px; } .stats { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:14px; margin-bottom:22px; } .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; } .text-link { color:#2f80ed; text-decoration:none; font-size:12px; white-space:nowrap; } .permission-note,.snapshot-note { color:#8592a6; font-size:11px; line-height:1.7; margin-top:18px; }
@media(max-width:1400px) { .stats { grid-template-columns:repeat(3,minmax(0,1fr)); } }
@media(max-width:900px) { .grid { grid-template-columns:minmax(0,1fr); } .heading { align-items:flex-start; flex-direction:column; } }
@media(max-width:550px) { .stats { grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; } h1 { font-size:26px; } }
:global(html:has(.dashboard)), :global(body:has(.dashboard)), :global(#app:has(.dashboard)) { min-width:320px; }
@media(max-width:700px) { :global(body:has(.dashboard) .app-sidebar) { display:none; } :global(body:has(.dashboard) .admin-layout__body) { margin-left:0; } :global(body:has(.dashboard) .admin-layout__main) { padding:16px; } }
@media(max-width:550px) {
  :global(body:has(.dashboard) .app-header) { height:auto; min-height:56px; padding:12px 16px; }
  :global(body:has(.dashboard) .app-header__left) { display:none; }
  :global(body:has(.dashboard) .app-header__right) { min-width:0; flex-wrap:wrap; gap:8px; font-size:12px; }
  :global(body:has(.dashboard) .environment-dot) { display:none; }
  :global(body:has(.dashboard) .app-header__right .el-button) { margin-left:0; }
}
</style>
