<script setup lang="ts">
import { ArrowRight, Expand, Fold, Key, SwitchButton } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'
import { changePassword } from '@/api/auth'
import ChangePasswordDialog from '@/layouts/components/ChangePasswordDialog.vue'

const route = useRoute()
const appStore = useAppStore()
const authStore = useAuthStore()
const router = useRouter()

const currentGroup = computed(() => String(route.meta.group || ''))
const currentTitle = computed(() => String(route.meta.title || ''))
const passwordDialogVisible = ref(false)
const passwordSubmitting = ref(false)

function logout() {
  authStore.logout()
  router.replace({ name: 'login' })
}

async function submitPassword(currentPassword: string, newPassword: string) {
  passwordSubmitting.value = true
  try {
    await changePassword(currentPassword, newPassword)
    ElMessage.success('密码修改成功，请重新登录')
    passwordDialogVisible.value = false
    logout()
  } catch {
    // Axios interceptor displays the backend error.
  } finally {
    passwordSubmitting.value = false
  }
}
</script>

<template>
  <header class="app-header">
    <div class="app-header__left">
      <el-button
        class="collapse-button"
        text
        :icon="appStore.sidebarCollapsed ? Expand : Fold"
        aria-label="切换侧边栏"
        @click="appStore.toggleSidebar"
      />
      <el-breadcrumb :separator-icon="ArrowRight">
        <el-breadcrumb-item v-if="currentGroup">{{ currentGroup }}</el-breadcrumb-item>
        <el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item>
      </el-breadcrumb>
    </div>
    <div class="app-header__right">
      <span class="environment-dot" />
      <span>{{ authStore.user?.username }}</span>
      <el-tag size="small" effect="plain">{{ authStore.user?.role }}</el-tag>
      <el-button link :icon="Key" @click="passwordDialogVisible = true">修改密码</el-button>
      <el-button link type="danger" :icon="SwitchButton" @click="logout">退出</el-button>
    </div>
    <ChangePasswordDialog v-model="passwordDialogVisible" :submitting="passwordSubmitting" @submit="submitPassword" />
  </header>
</template>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 24px 0 12px;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid #e8edf4;
  backdrop-filter: blur(10px);
}

.app-header__left,
.app-header__right {
  display: flex;
  align-items: center;
}

.app-header__left {
  gap: 12px;
}

.app-header__right {
  gap: 8px;
  color: #5f6b7a;
  font-size: 14px;
}

.collapse-button {
  width: 40px;
  height: 40px;
  font-size: 20px;
}

.environment-dot {
  width: 8px;
  height: 8px;
  background: #22a06b;
  border-radius: 50%;
  box-shadow: 0 0 0 4px rgba(34, 160, 107, 0.12);
}
</style>
