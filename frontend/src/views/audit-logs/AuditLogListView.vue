<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { onMounted, reactive, ref } from 'vue'

import { listAuditLogs } from '@/api/audit-logs'
import type { AuditLog } from '@/types/audit-log'

const loading = ref(false)
const logs = ref<AuditLog[]>([])
const filters = reactive({ action: '', object_type: '', user_id: '' })

const actionLabels: Record<string, string> = {
  LOGIN: '登录',
  DELIVERY_DEMAND_CREATED: '创建配送需求',
  DELIVERY_DEMAND_UPDATED: '修改配送需求',
  AUTO_DISPATCH_GENERATED: '自动派车',
  DISPATCH_DEMAND_MOVED: '人工调整',
  DISPATCH_PLAN_PUBLISHED: '发布方案',
  DISPATCH_PLAN_CANCELLED: '取消方案',
  DELIVERY_STARTED: '开始配送',
  DELIVERY_COMPLETED: '完成配送',
  DELIVERY_STOP_ARRIVED: '门店到店',
  DELIVERY_STOP_SIGNED: '门店签收',
  DELIVERY_STOP_FAILED: '配送失败',
  DELIVERY_PROOF_UPLOADED: '上传配送回单',
  USER_CREATED: '创建用户',
  USER_UPDATED: '修改用户权限',
  PASSWORD_CHANGED: '修改密码',
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date(value))
}

function formatChanges(value: Record<string, unknown> | null) {
  return value ? JSON.stringify(value, null, 2) : '—'
}

async function loadData() {
  loading.value = true
  try {
    logs.value = (await listAuditLogs({
      action: filters.action || undefined,
      object_type: filters.object_type.trim() || undefined,
      user_id: filters.user_id ? Number(filters.user_id) : undefined,
      offset: 0,
      limit: 100,
    })).data
  } catch {
    // 统一 Axios 拦截器负责展示后端错误。
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.action = ''
  filters.object_type = ''
  filters.user_id = ''
  loadData()
}

onMounted(loadData)
</script>

<template>
  <section class="audit-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">系统管理</p>
        <h1>审计日志</h1>
        <p>查看核心业务操作及必要变更信息。日志为只读数据。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
    </div>

    <el-card class="table-card" shadow="never">
      <el-form inline class="filters" @submit.prevent="loadData">
        <el-form-item label="操作类型">
          <el-select v-model="filters.action" clearable filterable placeholder="全部操作" style="width: 210px">
            <el-option v-for="(label, value) in actionLabels" :key="value" :label="`${label} / ${value}`" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="业务对象">
          <el-input v-model="filters.object_type" clearable placeholder="例如 DispatchPlan" />
        </el-form-item>
        <el-form-item label="用户 ID">
          <el-input v-model="filters.user_id" clearable placeholder="输入用户 ID" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" :loading="loading" native-type="submit">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="logs" row-key="id" stripe>
        <template #empty><el-empty description="暂无审计日志" :image-size="92" /></template>
        <el-table-column label="操作时间" width="180"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
        <el-table-column label="用户" min-width="145"><template #default="{ row }"><strong>{{ row.username }}</strong><div class="muted">ID: {{ row.user_id ?? '已删除' }}</div></template></el-table-column>
        <el-table-column label="操作" min-width="210"><template #default="{ row }"><el-tag effect="plain">{{ actionLabels[row.action] ?? row.action }}</el-tag><div class="muted">{{ row.action }}</div></template></el-table-column>
        <el-table-column label="业务对象" min-width="180"><template #default="{ row }">{{ row.object_type }}<span class="muted"> #{{ row.object_id ?? '—' }}</span></template></el-table-column>
        <el-table-column label="变更信息" min-width="360"><template #default="{ row }"><pre class="changes">{{ formatChanges(row.changes) }}</pre></template></el-table-column>
      </el-table>
      <div class="summary">当前显示最近 {{ logs.length }} 条，最多 100 条</div>
    </el-card>
  </section>
</template>

<style scoped>
.audit-page { max-width: 1600px; margin: 0 auto; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 22px; }
.eyebrow { margin: 0 0 7px !important; color: #2f80ed !important; font-size: 13px; font-weight: 600; }
.page-heading h1 { margin: 0; color: #172b4d; font-size: 28px; }
.page-heading p { margin: 9px 0 0; color: #6b778c; }
.table-card { border-color: #e4eaf2; border-radius: 14px; }
.filters { display: flex; align-items: flex-start; margin-bottom: 6px; }
.muted { margin-top: 3px; color: #8993a4; font-size: 12px; }
.changes { max-height: 150px; margin: 0; overflow: auto; color: #42526e; font: 12px/1.5 Consolas, monospace; white-space: pre-wrap; word-break: break-word; }
.summary { margin-top: 14px; color: #8993a4; font-size: 12px; text-align: right; }
</style>
