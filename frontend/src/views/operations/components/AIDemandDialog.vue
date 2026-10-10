<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { parseDemandText, confirmDemandBatch } from '@/api/ai-operations'
import { listStores } from '@/api/stores'
import type { Store } from '@/types/store'
import type { DemandPreview } from '@/types/ai-operations'
import { manualPreview, previewErrors, previewPayload } from './aiDemandPreview'

const props = defineProps<{ modelValue: boolean; date: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; created: [dates: string[]] }>()
const text = ref(''), rows = ref<DemandPreview[]>([]), notices = ref<string[]>([])
const parsing = ref(false), saving = ref(false), optionsLoading = ref(false), error = ref(''), optionError = ref('')
const stores = ref<Store[]>([]), anchor = ref('')
let epoch = 0, requestKey = '', requestBody = ''
let confirming = false
const sourceNames: Record<string, string> = { USER_EXPLICIT: '原文明确', DETERMINISTIC: '规则推导', SYSTEM_DEFAULT: '系统默认·待确认', MISSING: '缺失', MANUAL: '人工修改' }
const matchNames: Record<string, string> = { EXACT: '精确匹配', NORMALIZED: '规范化匹配', EXISTING_CODE: '已有编码匹配', BUSINESS_TERM: '业务词映射', AMBIGUOUS: '匹配不唯一', MANUAL_REQUIRED: '需要人工选择', SYSTEM_DEFAULT_CONFIRM: '系统默认·待确认' }
const valid = computed(() => rows.value.length > 0 && rows.value.length <= 30 && rows.value.every(r => !previewErrors(r).length))
function message(e: unknown) { return e && typeof e === 'object' && 'message' in e ? String(e.message) : '请求失败，请重试或手工补充' }
async function all<T>(fetch: (offset: number) => Promise<{ data: T[] }>, id: number) {
  const result: T[] = []
  for (let offset = 0; id === epoch; offset += 100) { const { data } = await fetch(offset); result.push(...data); if (data.length < 100) break }
  return result
}
watch(() => props.modelValue, async open => {
  const id = ++epoch
  if (!open) return
  error.value = ''; optionError.value = ''; optionsLoading.value = true
  try {
    const s = await all(o => listStores({ offset: o, limit: 100 }), id)
    if (id === epoch) { stores.value = s }
  } catch (e) { if (id === epoch) optionError.value = message(e) }
  finally { if (id === epoch) optionsLoading.value = false }
})
function edited(row: DemandPreview, field: string) { row.sources[field] = 'MANUAL' }
async function parse() {
  if (!text.value.trim()) return
  const id = ++epoch; parsing.value = true; error.value = ''; rows.value = []; notices.value = []
  try { const { data } = await parseDemandText(text.value); if (id === epoch) { rows.value = data.items; notices.value = data.notices; anchor.value = `解析基准：${data.base_date} · ${data.timezone} · 单位 kg` } }
  catch (e) { if (id === epoch) error.value = message(e) }
  finally { if (id === epoch) parsing.value = false }
}
async function save() {
  if (!valid.value || saving.value || confirming) return
  confirming = true
  try { await ElMessageBox.confirm(`确认创建 ${rows.value.length} 条待计划需求？请检查默认值及所有人工修改。不会自动派车。`, '人工确认', { type: 'warning' }) } catch { return } finally { confirming = false }
  const payload = rows.value.map(previewPayload), body = JSON.stringify(payload)
  // 未知网络结果重试同一请求键；人工修改后才产生新键。
  if (body !== requestBody) { requestKey = crypto.randomUUID(); requestBody = body }
  saving.value = true; error.value = ''
  try {
    const { data } = await confirmDemandBatch(requestKey, payload)
    ElMessage.success(`已创建 ${data.demand_ids.length} 条需求${data.replayed ? '（重复请求已安全复用）' : ''}`)
    emit('created', [...new Set(payload.map(x => x.date))]); emit('update:modelValue', false)
    rows.value = []; text.value = ''; requestBody = ''; requestKey = ''
  } catch (e) { error.value = message(e) }
  finally { saving.value = false }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="AI 智能录入 · 人工确认后创建" width="min(1120px, 96vw)" :close-on-click-modal="false" :before-close="(done: () => void) => { if (!saving && !parsing) done() }" @update:model-value="emit('update:modelValue', $event)">
    <el-alert title="AI 仅提取信息，不写数据库。模糊匹配与默认值必须人工核对；特殊要求未建模时不会自动保存。" type="info" :closable="false" />
    <el-input v-model="text" type="textarea" :rows="3" maxlength="6000" show-word-limit :disabled="parsing || saving" placeholder="例如：下周一上午给岳麓一店送320公斤，下午给河西二店送180公斤，上午需求设为加急。请使用已有门店名称。" class="text-input" />
    <div class="tools"><el-button type="primary" :loading="parsing" :disabled="saving || optionsLoading || !!optionError || !text.trim()" @click="parse">AI 智能识别</el-button><el-button :disabled="parsing || saving || rows.length >= 30" @click="rows.push(manualPreview(date))">手工补充一条</el-button><span>{{ anchor }}</span></div>
    <el-alert v-if="error || optionError" :title="error || optionError" type="error" :closable="false" description="解析失败不会创建需求，可重试或手工补充；资料加载失败时请关闭后重新打开。" />
    <p v-for="notice in notices" :key="notice" class="muted">{{ notice }}</p>
    <div v-loading="optionsLoading || parsing">
      <el-empty v-if="!rows.length" description="输入原文后识别，或手工补充需求" :image-size="64" />
      <el-card v-for="(row,index) in rows" :key="index" shadow="never" class="preview" :class="{ invalid: previewErrors(row).length }">
        <div class="row-title"><strong>需求 {{ index + 1 }} · {{ row.source_text }}</strong><el-button type="danger" link :disabled="saving" @click="rows.splice(index,1)">删除</el-button></div>
        <el-form label-position="top" :disabled="saving">
          <div class="fields">
            <el-form-item label="配送日期"><el-date-picker v-model="row.data.date" type="date" value-format="YYYY-MM-DD" @change="edited(row,'date')" /><small>{{ sourceNames[row.sources.date ?? 'MISSING'] }}</small></el-form-item>
            <el-form-item label="真实门店"><el-select v-model="row.data.store_id" filterable placeholder="请选择门店" @change="edited(row,'store_id')"><el-option v-for="s in stores" :key="s.id" :label="`${s.name} (${s.code})`" :value="s.id" /></el-select><small>{{ sourceNames[row.sources.store_id ?? 'MISSING'] }} · {{ matchNames[row.store_match.method] ?? row.store_match.method }}</small><small v-if="row.store_match.candidates.length">候选：{{ row.store_match.candidates.map(c => c.name).join('、') }}</small></el-form-item>
            <el-form-item label="配送时段"><el-select v-model="row.data.period" @change="edited(row,'period')"><el-option label="上午" value="MORNING" /><el-option label="下午" value="AFTERNOON" /></el-select><small>{{ sourceNames[row.sources.period ?? 'MISSING'] }}</small></el-form-item>
            <el-form-item label="货量 (kg)"><el-input v-model="row.data.quantity" @input="edited(row,'quantity')" /><small>{{ sourceNames[row.sources.quantity ?? 'MISSING'] }}</small></el-form-item>
            <el-form-item label="优先级"><el-select v-model="row.data.priority" @change="edited(row,'priority')"><el-option label="普通" value="NORMAL" /><el-option label="高" value="HIGH" /><el-option label="加急" value="URGENT" /></el-select><small>{{ sourceNames[row.sources.priority ?? 'MISSING'] }}</small></el-form-item>
          </div>
        </el-form>
        <p v-for="warning in row.warnings" :key="warning" class="warning">{{ warning }}</p>
        <p v-if="row.unsupported_remark" class="warning">未保存的特殊说明：{{ row.unsupported_remark }}</p>
        <p v-if="previewErrors(row).length" class="error-text">{{ previewErrors(row).join('；') }}</p>
      </el-card>
    </div>
    <template #footer><el-button :disabled="saving || parsing" @click="emit('update:modelValue',false)">取消</el-button><el-button type="primary" :loading="saving" :disabled="!valid || parsing || optionsLoading || !!optionError" @click="save">确认并创建 {{ rows.length }} 条需求</el-button></template>
  </el-dialog>
</template>
<style scoped>
.text-input,.preview { margin-top:16px }.tools,.row-title { display:flex;align-items:center;gap:12px;margin:14px 0 }.row-title { justify-content:space-between }.row-title strong { max-width:85%;overflow-wrap:anywhere }.fields { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0 18px }small { display:block;width:100%;line-height:1.6;color:#7b8aa2 }.muted,.tools span { color:#7b8aa2;font-size:12px }.warning { color:#b66d15 }.error-text { color:#d94747 }.invalid { border-color:#f0d7b0 }.temperatures { display:flex;gap:8px }:deep(.el-select),:deep(.el-date-editor) { width:100% }@media(max-width:750px){.fields{grid-template-columns:1fr}.tools{flex-wrap:wrap}}
</style>
