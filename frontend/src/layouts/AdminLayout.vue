<script setup lang="ts">
import { storeToRefs } from 'pinia'

import AppHeader from '@/layouts/components/AppHeader.vue'
import AppSidebar from '@/layouts/components/AppSidebar.vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
const { sidebarCollapsed } = storeToRefs(appStore)
</script>

<template>
  <div class="admin-layout">
    <AppSidebar />
    <div class="admin-layout__body" :class="{ 'is-collapsed': sidebarCollapsed }">
      <AppHeader />
      <main class="admin-layout__main">
        <RouterView v-slot="{ Component }">
          <Transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>
    </div>
  </div>
</template>

<style scoped>
.admin-layout {
  min-height: 100vh;
  background: #f4f7fb;
}

.admin-layout__body {
  min-height: 100vh;
  margin-left: 232px;
  transition: margin-left 0.2s ease;
}

.admin-layout__body.is-collapsed {
  margin-left: 72px;
}

.admin-layout__main {
  min-width: 0;
  padding: 24px;
}

.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.15s ease;
}

.page-fade-enter-from,
.page-fade-leave-to {
  opacity: 0;
}
</style>
