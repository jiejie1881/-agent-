<script setup lang="ts">
defineProps<{ title: string; subtitle?: string; loading?: boolean; error?: string }>()
</script>
<template>
  <section class="dashboard-panel" :aria-busy="loading">
    <header><div><h2>{{ title }}</h2><p v-if="subtitle">{{ subtitle }}</p></div><slot name="action" /></header>
    <div v-loading="loading" class="panel-body">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <slot v-else />
    </div>
  </section>
</template>
<style scoped>
.dashboard-panel { min-width: 0; background: #fff; border: 1px solid #e5ebf3; border-radius: 16px; overflow: hidden; }
header { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:22px 24px 0; }
h2 { margin:0; font-size:17px; color:#172b4d; } p { margin:7px 0 0; font-size:12px; line-height:1.6; color:#7a869a; }
.panel-body { padding:24px; min-height:100px; }
</style>
