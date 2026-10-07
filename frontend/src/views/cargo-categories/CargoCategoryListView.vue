<script setup lang="ts">
import { Edit, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { createCargoCategory, deactivateCargoCategory, listCargoCategories, updateCargoCategory } from '@/api/cargo-categories'
import { useAuthStore } from '@/stores/auth'
import type { CargoCategory, CargoCategoryPayload } from '@/types/cargo'
import CargoCategoryFormDialog from './components/CargoCategoryFormDialog.vue'

const authStore = useAuthStore()
const items = ref<CargoCategory[]>([]), keyword = ref(''), loading = ref(false), submitting = ref(false), visible = ref(false)
const editing = ref<CargoCategory | null>(null)
const filtered = computed(() => { const q = keyword.value.trim().toLowerCase(); return q ? items.value.filter((x) => `${x.code} ${x.name}`.toLowerCase().includes(q)) : items.value })
async function loadData() { loading.value = true; try { items.value = (await listCargoCategories()).data } catch {} finally { loading.value = false } }
function open(item: CargoCategory | null) { editing.value = item; visible.value = true }
async function save(payload: CargoCategoryPayload) { submitting.value = true; try { editing.value ? await updateCargoCategory(editing.value.id, payload) : await createCargoCategory(payload); ElMessage.success('货物分类保存成功'); visible.value = false; await loadData() } catch {} finally { submitting.value = false } }
async function deactivate(item: CargoCategory) { try { await ElMessageBox.confirm(`停用“${item.name}”后不能用于新需求和新能力配置，确认继续吗？`, '停用货物分类', { type: 'warning' }); await deactivateCargoCategory(item.id); ElMessage.success('货物分类已停用'); await loadData() } catch {} }
onMounted(loadData)
</script>

<template>
  <section class="master-page">
    <div class="heading"><div><p>基础资料</p><h1>货物分类管理</h1><span>维护单一货物类型；加急程度由配送需求优先级独立表达。</span></div><el-button v-if="authStore.canManageMasterData" type="primary" :icon="Plus" @click="open(null)">新增分类</el-button></div>
    <el-card shadow="never"><div class="toolbar"><el-input v-model="keyword" clearable placeholder="搜索编码或名称" /><el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button></div>
      <el-table v-loading="loading" :data="filtered" stripe><template #empty><el-empty description="暂无货物分类" /></template>
        <el-table-column prop="code" label="编码" width="180" /><el-table-column prop="name" label="名称" width="180" /><el-table-column prop="description" label="说明" min-width="240"><template #default="{ row }">{{ row.description || '—' }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag></template></el-table-column>
        <el-table-column v-if="authStore.canManageMasterData" label="操作" width="160" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="Edit" @click="open(row)">编辑</el-button><el-button v-if="row.is_active" link type="danger" @click="deactivate(row)">停用</el-button></template></el-table-column>
      </el-table>
    </el-card>
    <CargoCategoryFormDialog v-if="authStore.canManageMasterData" v-model="visible" :item="editing" :submitting="submitting" @submit="save" />
  </section>
</template>

<style scoped>
.master-page{max-width:1500px;margin:0 auto}.heading{display:flex;justify-content:space-between;margin-bottom:22px}.heading p{margin:0 0 7px;color:#2f80ed;font-size:13px;font-weight:600}.heading h1{margin:0;color:#172b4d}.heading span{display:block;margin-top:9px;color:#6b778c}.toolbar{display:flex;justify-content:space-between;gap:16px;margin-bottom:18px}.toolbar .el-input{width:380px}
</style>
