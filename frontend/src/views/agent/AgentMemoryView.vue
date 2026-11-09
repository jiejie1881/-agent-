<script setup lang="ts">
import { ref, onMounted } from 'vue'
import http from '@/api/http'
type Memory = { memory_id: string; content: string; memory_type: string; status: string; updated_at: string; source_conversation_id: number | null }
const rows = ref<Memory[]>([])
const content = ref('')
const editing = ref<string | null>(null)
const query = ref('')
const error = ref('')
const busy = ref(false)
async function run(action: () => Promise<unknown>) {
  busy.value = true; error.value = ''
  try { await action() } catch { error.value = '操作失败，请检查记忆是否启用及服务状态。' }
  finally { busy.value = false }
}
async function load() { rows.value = (await http.get<Memory[]>('/agent/memories')).data }
async function save() {
  const payload = { content: content.value, confirmed: true }
  if (editing.value) await http.put(`/agent/memories/${editing.value}`, payload)
  else await http.post('/agent/memories', payload)
  content.value = ''; editing.value = null; await load()
}
function edit(row: Memory) { editing.value = row.memory_id; content.value = row.content }
async function remove(id: string) { await http.delete(`/agent/memories/${id}`); await load() }
async function sync() { await http.post('/agent/memories/sync'); await load() }
onMounted(() => run(load))
</script>
<template>
  <section>
    <h2>我的长期记忆</h2>
    <p>仅保存已确认的偏好。请勿输入密码、密钥等敏感信息。</p>
    <el-alert v-if="error" :title="error" type="error" />
    <el-input v-model="content" type="textarea" maxlength="2000" placeholder="希望助手跨会话记住的偏好" />
    <el-button :disabled="busy || !content.trim()" @click="run(save)">确认保存</el-button>
    <el-button v-if="editing" @click="editing = null; content = ''">取消修改</el-button>
    <el-button :disabled="busy" @click="run(sync)">同步记忆索引</el-button>
    <el-input v-model="query" placeholder="筛选记忆" />
    <p>当前列表 {{ rows.length }} 条（最多100条）</p>
    <el-table :data="rows.filter(row => row.content.includes(query))">
      <el-table-column prop="content" label="内容" />
      <el-table-column prop="memory_type" label="类型" />
      <el-table-column prop="status" label="状态" />
      <el-table-column prop="updated_at" label="更新时间" />
      <el-table-column prop="source_conversation_id" label="来源会话" />
      <el-table-column label="操作"><template #default="scope">
        <el-button :disabled="busy" @click="edit(scope.row)">修改</el-button>
        <el-popconfirm title="确认删除此记忆？" @confirm="run(() => remove(scope.row.memory_id))">
          <template #reference><el-button :disabled="busy" type="danger">删除</el-button></template>
        </el-popconfirm>
      </template></el-table-column>
    </el-table>
  </section>
</template>
