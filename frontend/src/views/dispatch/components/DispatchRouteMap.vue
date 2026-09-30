<script setup lang="ts">
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import type { PersistedDispatchOrder } from '@/types/dispatch-plan'

const props = defineProps<{ orders: PersistedDispatchOrder[] }>()

const mapElement = ref<HTMLElement | null>(null)
const loading = ref(true)
const zoomLevel = ref(12)
const routeMetrics = ref<Array<{ orderId: number; distanceKm: number; durationMin: number; estimated: boolean }>>([])
let map: L.Map | null = null
let controller: AbortController | null = null
let initialCenter: L.LatLng | null = null

const deliveryCenter: L.LatLngTuple = [28.2044615, 112.8911692]
const colors = ['#2563eb', '#db2777', '#059669', '#d97706', '#7c3aed', '#0891b2', '#dc2626']

function storePoint(detail: PersistedDispatchOrder['details'][number]): L.LatLngTuple | null {
  if (detail.store_latitude == null || detail.store_longitude == null) return null
  return [Number(detail.store_latitude), Number(detail.store_longitude)]
}

function markerIcon(label: string, kind: 'dc' | 'store') {
  return L.divIcon({
    className: `demo-map-marker demo-map-marker--${kind}`,
    html: `<span>${label}</span>`,
    iconSize: kind === 'dc' ? [42, 42] : [30, 30],
    iconAnchor: kind === 'dc' ? [21, 21] : [15, 15],
  })
}

function escapeHtml(value: string | null) {
  const element = document.createElement('div')
  element.textContent = value ?? ''
  return element.innerHTML
}

function zoomIn() {
  map?.zoomIn(1, { animate: false })
}

function zoomOut() {
  map?.zoomOut(1, { animate: false })
}

function resetView() {
  if (map && initialCenter) map.setView(initialCenter, 12, { animate: false })
}

async function drawOrder(order: PersistedDispatchOrder, index: number, bounds: L.LatLngBounds) {
  if (!map) return
  const points = order.details.map(storePoint).filter((point): point is L.LatLngTuple => point !== null)
  if (!points.length) return
  const color = colors[index % colors.length]
  const locatedDetails = order.details.filter((item) => storePoint(item) !== null)
  points.forEach((point, pointIndex) => {
    const detail = locatedDetails[pointIndex]
    L.marker(point, { icon: markerIcon(String(pointIndex + 1), 'store') })
      .bindPopup(`<strong>${escapeHtml(detail.store_name)}</strong><br>${escapeHtml(detail.store_address)}<br>需求 #${detail.delivery_demand_id}`)
      .addTo(map!)
    bounds.extend(point)
  })

  const allPoints = [deliveryCenter, ...points, deliveryCenter]
  const coordinates = allPoints.map(([lat, lng]) => `${lng},${lat}`).join(';')
  try {
    const response = await fetch(
      `https://router.project-osrm.org/route/v1/driving/${coordinates}?overview=full&geometries=geojson&steps=false`,
      { signal: controller?.signal },
    )
    if (!response.ok) throw new Error(`OSRM ${response.status}`)
    const data = await response.json() as { routes?: Array<{ distance: number; duration: number; geometry: GeoJSON.LineString }> }
    const route = data.routes?.[0]
    if (!route) throw new Error('OSRM 未返回路线')
    L.geoJSON(route.geometry, { style: { color, weight: 5, opacity: 0.78 } }).addTo(map)
    routeMetrics.value.push({
      orderId: order.id,
      distanceKm: route.distance / 1000,
      durationMin: route.duration / 60,
      estimated: false,
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') return
    L.polyline(allPoints, { color, weight: 3, opacity: 0.6, dashArray: '7 7' }).addTo(map)
    routeMetrics.value.push({ orderId: order.id, distanceKm: 0, durationMin: 0, estimated: true })
  }
}

async function initializeMap() {
  await nextTick()
  if (!mapElement.value) return
  controller = new AbortController()
  const demoBounds = L.latLngBounds([deliveryCenter])
  props.orders.forEach((order) => {
    order.details.forEach((detail) => {
      const point = storePoint(detail)
      if (point) demoBounds.extend(point)
    })
  })
  // 边界需要大于宽屏地图视口，否则 Leaflet 会在边缘留下空白；
  // 这里仍只覆盖岳麓区 Demo 点位周边，不允许拖到跨市、跨省范围。
  const fixedBounds = demoBounds.pad(0.6)
  initialCenter = demoBounds.getCenter()
  map = L.map(mapElement.value, {
    zoomControl: false,
    minZoom: 12,
    maxZoom: 17,
    maxBounds: fixedBounds,
    maxBoundsViscosity: 1,
    scrollWheelZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    touchZoom: false,
    keyboard: false,
    zoomAnimation: false,
    fadeAnimation: false,
    markerZoomAnimation: false,
  })
  map.setView(initialCenter, 12, { animate: false })
  map.on('zoomend', () => {
    zoomLevel.value = map?.getZoom() ?? 12
  })
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
  }).addTo(map)
  L.marker(deliveryCenter, { icon: markerIcon('仓', 'dc') })
    .bindPopup('<strong>岳麓区域配送中心</strong><br>麓谷—梅溪湖之间（Demo）')
    .addTo(map)
  const bounds = L.latLngBounds([deliveryCenter])
  // 公共 Demo 路由服务没有 SLA，顺序请求可避免页面瞬间制造请求尖峰。
  for (const [index, order] of props.orders.entries()) {
    await drawOrder(order, index, bounds)
  }
  loading.value = false
}

onMounted(initializeMap)
onBeforeUnmount(() => {
  controller?.abort()
  map?.remove()
  map = null
})
</script>

<template>
  <el-card class="map-card" shadow="never">
    <template #header>
      <div class="map-header">
        <div>
          <h2>岳麓区配送路线</h2>
          <p>配送中心 → 门店 → 配送中心；道路路线由公共 OSRM Demo 服务计算。</p>
        </div>
        <div class="map-actions">
          <el-button-group>
            <el-button :disabled="zoomLevel >= 17" @click="zoomIn">放大</el-button>
            <el-button :disabled="zoomLevel <= 12" @click="zoomOut">缩小</el-button>
            <el-button @click="resetView">重置视图</el-button>
          </el-button-group>
          <el-tag type="info" effect="plain">非实时路况</el-tag>
        </div>
      </div>
    </template>
    <el-alert
      title="地图门店及业务数据均为模拟数据，仅用于系统功能演示。"
      type="warning"
      :closable="false"
      show-icon
    />
    <div ref="mapElement" v-loading="loading" class="route-map" />
    <div class="metric-list">
      <div v-for="metric in routeMetrics" :key="metric.orderId" class="metric-item">
        <strong>任务 #{{ metric.orderId }}</strong>
        <span v-if="!metric.estimated">{{ metric.distanceKm.toFixed(1) }} km · 约 {{ Math.ceil(metric.durationMin) }} 分钟</span>
        <span v-else class="metric-error">道路服务不可用，地图仅显示门店连线</span>
      </div>
    </div>
  </el-card>
</template>

<style scoped>
.map-card { margin-bottom: 22px; border-color: #dbe5f1; border-radius: 14px; }
.map-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.map-header h2 { margin: 0; color: #172b4d; font-size: 18px; }
.map-header p { margin: 5px 0 0; color: #7a869a; font-size: 12px; }
.map-actions { display: flex; align-items: center; gap: 10px; }
.route-map {
  position: relative;
  isolation: isolate;
  contain: layout paint;
  height: 520px;
  margin-top: 14px;
  overflow: hidden;
  border: 1px solid #dbe5f1;
  border-radius: 12px;
  clip-path: inset(0 round 12px);
}
.metric-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.metric-item { display: flex; flex-direction: column; gap: 4px; padding: 9px 11px; background: #f7f9fc; border-radius: 8px; font-size: 12px; }
.metric-item strong { color: #344563; }
.metric-item span { color: #5e6c84; }
.metric-item .metric-error { color: #b45309; }
:deep(.demo-map-marker) { display: grid; color: white; font-weight: 700; border: 2px solid white; border-radius: 50%; box-shadow: 0 2px 8px rgb(0 0 0 / 28%); place-items: center; }
:deep(.demo-map-marker--store) { background: #2563eb; }
:deep(.demo-map-marker--dc) { background: #dc2626; }
@media (max-width: 900px) { .map-header { align-items: flex-start; flex-direction: column; } .map-actions { width: 100%; flex-wrap: wrap; } .route-map { height: 400px; } .metric-list { grid-template-columns: 1fr; } }
</style>
