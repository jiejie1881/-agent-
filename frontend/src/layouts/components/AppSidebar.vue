<script setup lang="ts">
import {
  Calendar,
  Connection,
  Guide,
  MapLocation,
  OfficeBuilding,
  Operation,
  SetUp,
  Tickets,
  Van,
  UserFilled,
  DocumentChecked,
  ChatDotRound,
} from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const appStore = useAppStore()
const authStore = useAuthStore()
const { sidebarCollapsed } = storeToRefs(appStore)

const activeMenu = computed(() => {
  if (route.name === 'dispatch-plan-detail') {
    return '/dispatch/plans'
  }
  return route.path
})
</script>

<template>
  <aside class="app-sidebar" :class="{ 'is-collapsed': sidebarCollapsed }">
    <div class="brand">
      <div class="brand__mark"><Van /></div>
      <div v-show="!sidebarCollapsed" class="brand__text">
        <strong>物流智配</strong>
        <span>Dispatch Console</span>
      </div>
    </div>

    <el-scrollbar class="menu-scrollbar">
      <el-menu
        router
        :default-active="activeMenu"
        :collapse="sidebarCollapsed"
        :collapse-transition="false"
        class="sidebar-menu"
      >
        <el-sub-menu index="master">
          <template #title><el-icon><SetUp /></el-icon><span>基础资料</span></template>
          <el-menu-item index="/master/terrains"><el-icon><MapLocation /></el-icon><span>地形管理</span></el-menu-item>
          <el-menu-item index="/master/routes"><el-icon><Guide /></el-icon><span>线路管理</span></el-menu-item>
          <el-menu-item index="/master/stores"><el-icon><OfficeBuilding /></el-icon><span>门店管理</span></el-menu-item>
          <el-menu-item index="/master/vehicle-types"><el-icon><Connection /></el-icon><span>车型管理</span></el-menu-item>
          <el-menu-item index="/master/vehicles"><el-icon><Van /></el-icon><span>车辆管理</span></el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="operations">
          <template #title><el-icon><Calendar /></el-icon><span>每日运营</span></template>
          <el-menu-item index="/operations/vehicle-attendances"><el-icon><Tickets /></el-icon><span>车辆出勤</span></el-menu-item>
          <el-menu-item index="/operations/drivers"><el-icon><UserFilled /></el-icon><span>司机与排班</span></el-menu-item>
          <el-menu-item index="/operations/leave-approval"><el-icon><DocumentChecked /></el-icon><span>请假审批</span></el-menu-item>
          <el-menu-item index="/operations/substitutions"><el-icon><UserFilled /></el-icon><span>代班调度</span></el-menu-item>
          <el-menu-item index="/operations/delivery-demands"><el-icon><Operation /></el-icon><span>配送需求</span></el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="dispatch">
          <el-menu-item index="/dispatch/auto"><el-icon><Van /></el-icon><span>自动派车</span></el-menu-item>
          <el-menu-item index="/dispatch/plans"><el-icon><Tickets /></el-icon><span>方案列表</span></el-menu-item>
          <el-menu-item index="/dispatch/exceptions"><el-icon><DocumentChecked /></el-icon><span>每日异常</span></el-menu-item>
        </el-sub-menu>

        <el-menu-item index="/agent">
          <el-icon><ChatDotRound /></el-icon><span>智能调度助手</span>
        </el-menu-item>

        <el-sub-menu v-if="authStore.user?.role === 'ADMIN'" index="system">
          <template #title><el-icon><UserFilled /></el-icon><span>系统管理</span></template>
          <el-menu-item index="/system/users"><el-icon><UserFilled /></el-icon><span>用户与权限</span></el-menu-item>
          <el-menu-item index="/system/audit-logs"><el-icon><DocumentChecked /></el-icon><span>审计日志</span></el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-scrollbar>
  </aside>
</template>

<style scoped>
.app-sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 30;
  width: 232px;
  overflow: hidden;
  color: #dce6f3;
  background: linear-gradient(180deg, #172b4d 0%, #0e1d35 100%);
  box-shadow: 8px 0 24px rgba(15, 35, 65, 0.12);
  transition: width 0.2s ease;
}

.app-sidebar.is-collapsed {
  width: 72px;
}

.brand {
  display: flex;
  align-items: center;
  height: 64px;
  padding: 0 17px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.brand__mark {
  display: grid;
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  color: #fff;
  background: #2f80ed;
  border-radius: 11px;
  place-items: center;
}

.brand__mark :deep(svg) {
  width: 23px;
  height: 23px;
}

.brand__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  margin-left: 11px;
  white-space: nowrap;
}

.brand__text strong {
  color: #fff;
  font-size: 16px;
  letter-spacing: 1px;
}

.brand__text span {
  margin-top: 2px;
  color: #8fa7c4;
  font-size: 10px;
}

.menu-scrollbar {
  height: calc(100vh - 64px);
}

.sidebar-menu {
  width: 100%;
  padding: 12px 8px;
  background: transparent;
  border-right: 0;
}

.sidebar-menu:not(.el-menu--collapse) {
  width: 232px;
}

.sidebar-menu :deep(.el-sub-menu__title),
.sidebar-menu :deep(.el-menu-item) {
  height: 46px;
  margin: 3px 0;
  color: #aebed1;
  border-radius: 8px;
}

.sidebar-menu :deep(.el-sub-menu__title:hover),
.sidebar-menu :deep(.el-menu-item:hover) {
  color: #fff;
  background: rgba(255, 255, 255, 0.07);
}

.sidebar-menu :deep(.el-menu),
.sidebar-menu :deep(.el-menu-item.is-active) {
  background: transparent;
}

.sidebar-menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: #2f80ed;
}
</style>
