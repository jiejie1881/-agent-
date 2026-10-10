// Display references are derived from real keys; API payloads always retain numeric IDs.
export const typeNames: Record<string, string> = { FOUR_METER: '4.2米厢式货车', BIG_VAN: '大型面包车', SMALL_VAN: '小型面包车' }
export const businessRef = (prefix: string, id: number | null | undefined, day?: string) => id == null ? '未记录' : `${prefix}-${day ? day.replace(/-/g, '') + '-' : ''}${String(id).padStart(3, '0')}`
export const planRef = (day: string, version: number) => `DP-${day.replace(/-/g, '')}-V${version}`
export const typeLabel = (code: string, configuredName?: string) => typeNames[code] ?? configuredName ?? '车型未记录'
