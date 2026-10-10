<script setup lang="ts">
import type { Component } from 'vue'
defineProps<{ title: string; value: string; unit?: string; description: string; icon: Component; tone?: string; loading?: boolean; error?: string }>()
</script>
<template>
  <article v-loading="loading" class="stat-card" :style="{ '--tone': tone || '#2f80ed' }" :aria-busy="loading">
    <div class="stat-heading"><span>{{ title }}</span><el-icon><component :is="icon" /></el-icon></div>
    <div class="stat-value">{{ loading ? '—' : error ? '加载失败' : value }}<small v-if="!loading && !error">{{ unit }}</small></div>
    <p>{{ error || description }}</p>
  </article>
</template>
<style scoped>
.stat-card { padding:20px; min-width:0; background:#fff; border:1px solid #e5ebf3; border-radius:14px; }
.stat-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; color:#63738c; font-size:13px; }
.el-icon { padding:9px; width:36px; height:36px; color:var(--tone); background:color-mix(in srgb,var(--tone) 9%,white); border-radius:11px; }
.stat-value { margin:14px 0 10px; color:#172b4d; font-size:28px; font-weight:750; letter-spacing:-.7px; overflow-wrap:anywhere; } small { margin-left:6px; font-size:12px; font-weight:400; color:#8592a6; letter-spacing:0; }
p { margin:0; font-size:11px; line-height:1.7; color:#8592a6; }
</style>
