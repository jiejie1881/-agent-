import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const component = readFileSync(new URL('../src/views/dispatch/components/DispatchRouteMap.vue', import.meta.url), 'utf8')
const leafletSource = readFileSync(new URL('../node_modules/leaflet/dist/leaflet-src.js', import.meta.url), 'utf8')
const image = name => 'data:image/png;base64,' + readFileSync(new URL(`../node_modules/leaflet/dist/images/${name}`, import.meta.url)).toString('base64')

// Exercise the installed Leaflet implementation with a minimal DOM shim.
// This is an offline unit test, not browser rendering or image decoding.
function setup(retina = false) {
  const element = tagName => ({ tagName: tagName.toUpperCase(), style: {}, children: [],
    appendChild(child) { this.children.push(child) }, removeChild() {}, setAttribute() {},
    getContext() {}, addEventListener() {}, removeEventListener() {} })
  const document = { documentElement: element('html'), body: element('body'),
    createElement: element, createElementNS: (_, name) => element(name), querySelector: () => null,
    addEventListener() {}, removeEventListener() {},
    defaultView: { getComputedStyle: () => ({ backgroundImage: `url("${image('marker-icon.png')}")` }) } }
  const window = { document, devicePixelRatio: retina ? 2 : 1, screen: {},
    setTimeout, clearTimeout, addEventListener() {}, removeEventListener() {} }
  const module = { exports: {} }
  const context = vm.createContext({ window, document, navigator: { userAgent: 'unit-test', platform: 'Win32' },
    module, exports: module.exports, console, setTimeout, clearTimeout })
  vm.runInContext(leafletSource, context)
  context.L = context.exports
  for (const match of component.matchAll(/import (\w+) from 'leaflet\/dist\/images\/([^']+)\?url'/g)) {
    context[match[1]] = image(match[2])
  }
  const definition = component.match(/const storeMarkerIcon=(L\.icon\(\{[\s\S]*?\}\))/)
  assert.ok(definition, 'all map markers need an explicit bundled icon')
  const icon = vm.runInContext(definition[1], context)
  return { L: context.L, icon }
}

test('reproduces Leaflet default detection failure for Vite inline image URLs', () => {
  const { L } = setup()
  assert.equal(new L.Icon.Default()._stripUrl(`url("${image('marker-icon.png')}")`), null)
  assert.equal(new L.Icon.Default()._stripUrl('url("/assets/marker-icon.png")'), '/assets/')
  assert.match(leafletSource, /alt: 'Marker'/)
})

test('ordinary marker uses the exact packaged local PNG without default path detection', () => {
  const { L, icon } = setup()
  L.Icon.Default.imagePath = '/incorrect-path/'
  const node = icon.createIcon()
  assert.equal(node.src, image('marker-icon.png'))
  assert.equal(node.style.width, '25px')
  assert.equal(node.style.height, '41px')
  assert.equal(node.style.marginLeft, '-12px')
  assert.equal(node.style.marginTop, '-41px')
})

test('retina markers use the packaged double-resolution PNG', () => {
  const { icon } = setup(true)
  assert.equal(icon.createIcon().src, image('marker-icon-2x.png'))
})

test('marker shadow also uses bundled local bytes', () => {
  const { icon } = setup()
  const shadow = icon.createShadow()
  assert.equal(shadow.src, image('marker-shadow.png'))
  assert.equal(shadow.style.width, '41px')
  assert.equal(shadow.style.height, '41px')
})

test('all markers share the icon without changing coordinates or popup data', () => {
  const { L, icon } = setup()
  const points = [[28.199639, 112.901389], [28.18392, 112.93517], [28.125309, 112.95676]]
  for (const [index, point] of points.entries()) {
    const marker = L.marker(point, { icon }).bindPopup(`门店-${index}`)
    assert.equal(marker.options.icon, icon)
    assert.equal(marker.getLatLng().lat, point[0])
    assert.equal(marker.getLatLng().lng, point[1])
    assert.equal(marker.getPopup().getContent(), `门店-${index}`)
    assert.equal(marker.options.icon.createIcon().src, image('marker-icon.png'))
  }
  assert.match(component, /L\.marker\(points\[index\],\{icon:storeMarkerIcon\}\)/)
})

test('map retains coordinates, tiles, viewport, refresh and teardown hooks', () => {
  for (const pattern of [/store_latitude/, /store_longitude/, /zoomControl:true/, /fitBounds/,
    /L\.tileLayer\(tileUrl/, /watch\(\(\)=>props\.orders,draw,\{deep:true\}\)/,
    /onBeforeUnmount/, /map\?\.remove\(\)/, /escapeHtml\(detail\.store_name\)/]) {
    assert.match(component, pattern)
  }
  assert.equal([...component.matchAll(/import \w+ from 'leaflet\/dist\/images\//g)].length, 3)
  assert.doesNotMatch(component, /Icon\.Default\.prototype|delete .*_getIconUrl|https?:.*marker.*\.png/)
})
