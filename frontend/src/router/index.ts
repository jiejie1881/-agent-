import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import AdminLayout from '@/layouts/AdminLayout.vue'
import StoreListView from '@/views/stores/StoreListView.vue'
import TerrainListView from '@/views/terrains/TerrainListView.vue'
import RouteListView from '@/views/routes/RouteListView.vue'
import VehicleTypeListView from '@/views/vehicle-types/VehicleTypeListView.vue'
import VehicleListView from '@/views/vehicles/VehicleListView.vue'
import DeliveryDemandView from '@/views/operations/DeliveryDemandView.vue'
import VehicleAttendanceView from '@/views/operations/VehicleAttendanceView.vue'
import AutoDispatchView from '@/views/dispatch/AutoDispatchView.vue'
import DispatchPlanListView from '@/views/dispatch/DispatchPlanListView.vue'
import DispatchPlanDetailView from '@/views/dispatch/DispatchPlanDetailView.vue'
import LoginView from '@/views/LoginView.vue'
import { useAuthStore } from '@/stores/auth'
import UserListView from '@/views/users/UserListView.vue'
import AuditLogListView from '@/views/audit-logs/AuditLogListView.vue'
import AgentChatView from '@/views/agent/AgentChatView.vue'
import DailyExceptionView from '@/views/dispatch/DailyExceptionView.vue'

const children: RouteRecordRaw[] = [
  { path: 'dispatch/quality', name: 'dispatch-quality', component: () => import('@/views/dispatch/DispatchQualityView.vue'), meta: { title: '调度质量报告', group: '派车中心' } },
  { path: 'operations/leave-approval', component: () => import('@/views/drivers/DriverLeaveView.vue'), meta: { title: '请假审批', group: '每日运营' } },
  { path: 'operations/substitutions', component: () => import('@/views/drivers/DriverLeaveView.vue'), props: { mode: 'substitution' }, meta: { title: '代班调度', group: '每日运营' } },
  { path: 'operations/drivers', name: 'driver-scheduling', component: () => import('@/views/drivers/DriverSchedulingView.vue'), meta: { title: '司机与排班', group: '每日运营' } },
  {
    path: 'dashboard',
    name: 'dashboard',
    component: () => import('@/views/dashboard/DashboardView.vue'),
    meta: { title: '运营总览', group: '运营中心' },
  },
  {
    path: 'master/terrains',
    name: 'terrains',
    component: TerrainListView,
    meta: { title: '地形管理', group: '基础资料' },
  },
  {
    path: 'master/routes',
    name: 'routes',
    component: RouteListView,
    meta: { title: '线路管理', group: '基础资料' },
  },
  {
    path: 'master/stores',
    name: 'stores',
    component: StoreListView,
    meta: { title: '门店管理', group: '基础资料' },
  },
  {
    path: 'master/vehicle-types',
    name: 'vehicle-types',
    component: VehicleTypeListView,
    meta: { title: '车型管理', group: '基础资料' },
  },
  {
    path: 'master/vehicles',
    name: 'vehicles',
    component: VehicleListView,
    meta: { title: '车辆管理', group: '基础资料' },
  },
  {
    path: 'operations/vehicle-attendances',
    name: 'vehicle-attendances',
    component: VehicleAttendanceView,
    meta: { title: '车辆出勤', group: '每日运营' },
  },
  {
    path: 'operations/delivery-demands',
    name: 'delivery-demands',
    component: DeliveryDemandView,
    meta: { title: '配送需求', group: '每日运营' },
  },
  {
    path: 'dispatch/auto',
    name: 'auto-dispatch',
    component: AutoDispatchView,
    meta: { title: '自动派车', group: '派车中心' },
  },
  {
    path: 'dispatch/exceptions',
    name: 'daily-exceptions',
    component: DailyExceptionView,
    meta: { title: '每日异常工作台', group: '派车中心' },
  },
  {
    path: 'dispatch/plans',
    name: 'dispatch-plans',
    component: DispatchPlanListView,
    meta: { title: '方案列表', group: '派车中心' },
  },
  {
    path: 'dispatch/plans/:planId',
    name: 'dispatch-plan-detail',
    component: DispatchPlanDetailView,
    meta: { title: '方案详情', group: '派车中心' },
  },
  {
    path: 'agent',
    name: 'agent-chat',
    component: AgentChatView,
    meta: { title: '智能调度助手', group: '智能助手' },
  },
  {
    path: 'system/users',
    name: 'users',
    component: UserListView,
    meta: { title: '用户与权限', group: '系统管理', requiresAdmin: true },
  },
  {
    path: 'system/audit-logs',
    name: 'audit-logs',
    component: AuditLogListView,
    meta: { title: '审计日志', group: '系统管理', requiresAdmin: true },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { title: '登录', public: true },
    },
    {
      path: '/',
      component: AdminLayout,
      redirect: '/dashboard',
      children,
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard',
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  await authStore.initialize()
  if (to.meta.public) {
    return to.name === 'login' && authStore.isAuthenticated ? { path: '/' } : true
  }
  if (!authStore.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && authStore.user?.role !== 'ADMIN') {
    return { path: '/' }
  }
  return true
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} - 物流车辆智能分配系统` : '物流车辆智能分配系统'
})

export default router
