<script setup lang="ts">
import { Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function submit() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await authStore.login(form.username.trim(), form.password)
    if (authStore.user?.role === 'DRIVER') {
      authStore.logout()
      ElMessage.warning('司机账号请使用司机端登录，不能进入调度管理后台')
      return
    }
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch {
    // Axios interceptor displays the authentication error.
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="login-brand">物流智配</div>
      <h1>登录调度后台</h1>
      <p>使用系统账号进入物流车辆智能分配系统</p>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :prefix-icon="User" size="large" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            :prefix-icon="Lock"
            type="password"
            show-password
            size="large"
            autocomplete="current-password"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" size="large" native-type="submit" :loading="loading">
          登录
        </el-button>
      </el-form>
    </section>
  </main>
</template>

<style scoped>
.login-page { display: grid; min-height: 100vh; padding: 24px; background: radial-gradient(circle at 20% 20%, #e7f2ff, transparent 35%), #f3f6fb; place-items: center; }
.login-panel { width: min(420px, 100%); padding: 40px; background: #fff; border: 1px solid #e2e8f2; border-radius: 18px; box-shadow: 0 22px 60px rgba(23, 43, 77, 0.12); }
.login-brand { display: inline-block; padding: 8px 12px; color: #fff; font-weight: 700; background: #2f80ed; border-radius: 9px; }
h1 { margin: 24px 0 8px; color: #172b4d; font-size: 28px; }
p { margin: 0 0 28px; color: #7a869a; }
.el-button { width: 100%; margin-top: 6px; }
</style>
