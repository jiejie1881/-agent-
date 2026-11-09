<script setup lang="ts">
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import markerIconUrl from 'leaflet/dist/images/marker-icon.png?url'
import markerIconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png?url'
import markerShadowUrl from 'leaflet/dist/images/marker-shadow.png?url'
import {computed, nextTick, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import type {PersistedDispatchOrder} from '@/types/dispatch-plan'
const props=defineProps<{orders:PersistedDispatchOrder[]}>()
const element=ref<HTMLElement|null>(null), tileError=ref(false)
const located=computed(() => props.orders.flatMap(order=>order.details.filter(d=>d.store_latitude!=null && d.store_longitude!=null).map(d=>({order,detail:d}))))
const missing=computed(() => props.orders.reduce((n,o)=>n+o.details.length,0)-located.value.length)
const tileUrl=import.meta.env.VITE_MAP_TILE_URL as string | undefined
let map:L.Map|null=null
// Explicit Vite asset imports avoid Leaflet's CSS filename-based path detection.
const storeMarkerIcon=L.icon({
  iconUrl:markerIconUrl,iconRetinaUrl:markerIconRetinaUrl,shadowUrl:markerShadowUrl,
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],tooltipAnchor:[16,-28],shadowSize:[41,41],
})
function escapeHtml(text:string|null){const e=document.createElement('div');e.textContent=text ?? '';return e.innerHTML}
async function draw(){
  await nextTick();map?.remove();map=null;tileError.value=false
  if(!element.value || !located.value.length)return
  const points=located.value.map(item=>L.latLng(Number(item.detail.store_latitude),Number(item.detail.store_longitude)))
  map=L.map(element.value,{zoomControl:true});map.fitBounds(L.latLngBounds(points),{padding:[30,30],maxZoom:14})
  // The tile provider is an explicit deployment choice; no routing service receives store coordinates.
  if(tileUrl?.startsWith('https://'))L.tileLayer(tileUrl,{maxZoom:19,attribution:import.meta.env.VITE_MAP_ATTRIBUTION ?? ''}).on('tileerror',()=>{tileError.value=true}).addTo(map)
  located.value.forEach(({order,detail},index)=>{
    L.marker(points[index],{icon:storeMarkerIcon}).bindPopup(`<strong>${escapeHtml(detail.store_name)}</strong><br>${escapeHtml(detail.store_address)}<br>任务 #${order.id} · 需求 #${detail.delivery_demand_id}`).addTo(map!)
  })
}
onMounted(draw);watch(()=>props.orders,draw,{deep:true});onBeforeUnmount(()=>{map?.remove();map=null})
</script>
<template><el-card shadow="never"><h2>配送门店位置</h2><p>仅显示数据库中已录入的门店坐标；不推断仓库位置，不计算道路距离或配送时间。</p>
  <el-alert v-if="!tileUrl" title="未配置地图底图，位置标记仍可查看。底图服务需由部署管理员配置。" type="info" :closable="false" />
  <el-alert v-if="tileError" title="地图底图加载失败，请检查网络或底图服务配置。" type="warning" :closable="false" />
  <p v-if="missing">{{ missing }} 个停靠点未填写坐标，无法显示位置。</p>
  <div v-if="located.length" ref="element" class="map" /><el-empty v-else description="暂无可显示的门店坐标，请维护门店经纬度" />
</el-card></template>
<style scoped>.el-card{margin-bottom:20px}.map{height:480px;isolation:isolate;background:#f0f3f7}p{color:#56657a}</style>
