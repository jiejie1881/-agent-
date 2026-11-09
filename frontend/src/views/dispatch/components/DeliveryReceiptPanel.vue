<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { loadProofImage, reviewProof } from '@/api/delivery-proofs'
import type { ApiError } from '@/api/http'
import type { PersistedDispatchOrderDetail } from '@/types/dispatch-plan'
import type { DeliveryProof } from '@/types/delivery-proof'

const props = defineProps<{ stops: PersistedDispatchOrderDetail[] }>()
const emit = defineEmits<{ changed: [] }>()
const auth = useAuthStore()
const expanded = ref(false)
const loading = ref(false)
const pending = ref<number | null>(null)
const images = ref<Record<number, string>>({})
const errors = ref<Record<number, string>>({})
const labels = { PENDING: '待审核', APPROVED: '已通过', REJECTED: '已驳回' }
let generation = 0
function releaseImages() {
  Object.values(images.value).forEach(URL.revokeObjectURL)
  images.value = {}
}
async function loadImages() {
  const version = ++generation
  releaseImages()
  errors.value = {}
  loading.value = true
  await Promise.all(props.stops.flatMap(stop => stop.proofs || []).map(async proof => {
    try {
      const url = await loadProofImage(proof.id)
      if (version === generation && auth.isAuthenticated) images.value[proof.id] = url
      else URL.revokeObjectURL(url)
    } catch (error) {
      if (version === generation) errors.value[proof.id] = (error as ApiError).message || '图片加载失败'
    }
  }))
  if (version === generation) loading.value = false
}
function isHistorical(stop: PersistedDispatchOrderDetail, proof: DeliveryProof) {
  return stop.proofs.some(item => item.replaces_proof_id === proof.id)
}
async function review(proof: DeliveryProof, decision: 'APPROVED' | 'REJECTED') {
  if (auth.user?.role !== 'ADMIN' || pending.value) return
  let reason: string | undefined
  try {
    if (decision === 'REJECTED') {
      const result = await ElMessageBox.prompt('请填写驳回原因，司机将根据此原因补传照片。', '驳回回单', {
        inputValidator: value => Boolean(value?.trim()) || '必须填写驳回原因', inputType: 'textarea',
      })
      reason = result.value.trim()
    } else await ElMessageBox.confirm('确认通过这张回单？审核记录将被保留。', '审核回单')
  } catch { return }
  pending.value = proof.id
  try {
    const result = await reviewProof(proof.id, decision, reason)
    Object.assign(proof, result.data)
    ElMessage.success('审核已保存')
    emit('changed')
  } catch (error) { ElMessage.error((error as ApiError).message || '审核失败') }
  finally { pending.value = null }
}
watch(() => props.stops, () => { if (expanded.value) void loadImages() })
watch(() => auth.isAuthenticated, value => { if (!value) { generation++; releaseImages() } })
onBeforeUnmount(() => { generation++; releaseImages() })
function toggle() { expanded.value = !expanded.value; if (expanded.value) void loadImages() }
</script>

<template>
  <div class="receipt-panel">
    <el-button @click="toggle">{{ expanded ? '收起' : '查看' }}门店签收与回单</el-button>
    <template v-if="expanded">
      <p class="hint">配送完成与照片审核独立；每张照片单独审核，补传保留原件和历史记录。</p>
      <el-button size="small" :loading="loading" @click="loadImages">刷新图片</el-button>
      <div v-for="stop in stops" :key="stop.id" class="receipt-stop">
        <h4>{{ stop.store_name }} · {{ ({ PENDING: '待配送', ARRIVED: '已到店', SIGNED: '已签收', FAILED: '配送失败' })[stop.delivery_status] }}</h4>
        <p>签收人：{{ stop.receiver_name || '—' }}　联系电话：{{ stop.receiver_phone || '—' }}　签收时间：{{ stop.signed_at || '—' }}</p>
        <p v-if="stop.driver_remark">司机备注：{{ stop.driver_remark }}</p>
        <el-empty v-if="!stop.proofs?.length" description="暂无回单照片" :image-size="44" />
        <div class="photos">
          <div v-for="proof in stop.proofs" :key="proof.id" class="photo">
            <el-image v-if="images[proof.id]" :src="images[proof.id]" :preview-src-list="[images[proof.id]!]" preview-teleported fit="cover" />
            <div v-else class="placeholder">{{ errors[proof.id] || '加载图片中…' }}</div>
            <el-tag :type="proof.review_status === 'APPROVED' ? 'success' : proof.review_status === 'REJECTED' ? 'danger' : 'warning'">{{ labels[proof.review_status] }}</el-tag>
            <span v-if="isHistorical(stop, proof)">历史原件（已补传）</span>
            <span v-else-if="proof.replaces_proof_id">补传照片</span>
            <div v-if="auth.user?.role === 'ADMIN' && stop.delivery_status === 'SIGNED' && proof.review_status === 'PENDING' && !isHistorical(stop, proof)" class="buttons">
              <el-button size="small" type="success" :disabled="pending !== null" @click="review(proof, 'APPROVED')">通过</el-button>
              <el-button size="small" type="danger" :disabled="pending !== null" @click="review(proof, 'REJECTED')">驳回</el-button>
            </div>
            <div v-for="record in proof.reviews" :key="record.id" class="history">{{ record.reviewer_username }} · {{ record.decision === 'APPROVED' ? '通过' : '驳回' }} · {{ record.created_at }}<br>{{ record.reason }}</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.receipt-panel { margin-top: 16px; }.hint,.history { color: #66758c; font-size: 12px; }
.receipt-stop { padding: 12px 0; border-bottom: 1px solid #e6ebf2; }.receipt-stop p { font-size: 13px; }
.photos { display: flex; flex-wrap: wrap; gap: 16px; }.photo { width: 190px; display: flex; flex-direction: column; gap: 8px; }
.el-image,.placeholder { width: 190px; height: 140px; border-radius: 8px; background: #f3f6fa; }.placeholder { display: grid; place-items: center; font-size: 12px; }
.buttons { display: flex; }.history { overflow-wrap: anywhere; }
</style>
