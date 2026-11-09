// Display references are derived from real keys; API payloads always retain numeric IDs.
export const typeNames: Record<string, string> = { FOUR_METER: '4.2米厢式货车', BIG_VAN: '大型面包车', SMALL_VAN: '小型面包车' }
const prefixes: Record<string,string> = {DRV:'司机',DEM:'需求',TASK:'任务',LV:'请假',ST:'门店',RT:'线路',VH:'车辆'}
export const businessRef = (prefix: string, id: number | null | undefined, day?: string) => id == null ? '未记录' : `${prefixes[prefix] ?? prefix}-${day ? day.replace(/-/g, '') + '-' : ''}${String(id).padStart(3, '0')}`
export const planRef = (day: string, version: number) => `方案-${day.replace(/-/g, '')}-${String(version).padStart(3, '0')}`
export const typeLabel = (code: string, configuredName?: string) => configuredName ?? typeNames[code] ?? '车型未记录'

export const periodLabel = (value: string) => ({MORNING:'上午',AFTERNOON:'下午'} as Record<string,string>)[value] ?? value
export const statusLabel = (value: string) => ({DRAFT:'草稿',PUBLISHED:'已发布',CANCELLED:'已取消',IN_DELIVERY:'配送中',COMPLETED:'已完成',PENDING:'待处理',SIGNED:'已签收',FAILED:'配送失败'} as Record<string,string>)[value] ?? value
