<script setup lang="ts">
import { Clock, Connection } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const title = computed(() => String(route.meta.title || '页面'))
const group = computed(() => String(route.meta.group || ''))
</script>

<template>
  <section class="placeholder-page">
    <div class="page-heading">
      <div>
        <p class="page-heading__eyebrow">{{ group }}</p>
        <h1>{{ title }}</h1>
        <p>页面路由与后台框架已经就绪，业务功能将在后续阶段接入现有 FastAPI 接口。</p>
      </div>
      <el-tag type="info" effect="plain" round>第一阶段</el-tag>
    </div>

    <el-card class="placeholder-card" shadow="never">
      <el-icon class="placeholder-card__icon"><Connection /></el-icon>
      <h2>{{ title }}</h2>
      <p>当前仅提供页面入口，不包含 Mock 数据，也尚未发起业务 API 请求。</p>
      <div class="placeholder-card__status">
        <el-icon><Clock /></el-icon>
        <span>等待后续页面开发</span>
      </div>
    </el-card>
  </section>
</template>

<style scoped>
.placeholder-page {
  max-width: 1440px;
  margin: 0 auto;
}

.page-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 22px;
}

.page-heading__eyebrow {
  margin: 0 0 7px;
  color: #2f80ed;
  font-size: 13px;
  font-weight: 600;
}

.page-heading h1 {
  margin: 0;
  color: #172b4d;
  font-size: 28px;
}

.page-heading p:not(.page-heading__eyebrow) {
  margin: 9px 0 0;
  color: #6b778c;
}

.placeholder-card {
  min-height: 420px;
  border-color: #e4eaf2;
  border-radius: 14px;
}

.placeholder-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 370px;
  text-align: center;
}

.placeholder-card__icon {
  width: 64px;
  height: 64px;
  color: #2f80ed;
  font-size: 34px;
  background: #edf5ff;
  border-radius: 18px;
}

.placeholder-card h2 {
  margin: 20px 0 8px;
  color: #172b4d;
}

.placeholder-card p {
  max-width: 520px;
  margin: 0;
  color: #7a869a;
  line-height: 1.7;
}

.placeholder-card__status {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 20px;
  padding: 8px 13px;
  color: #6b778c;
  font-size: 13px;
  background: #f4f6f8;
  border-radius: 999px;
}
</style>
