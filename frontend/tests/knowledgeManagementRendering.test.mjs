import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'
import * as Vue from 'vue'
import {parse, compileScript} from '@vue/compiler-sfc'
import {renderToString} from '@vue/server-renderer'

async function render(role) {
  const source = readFileSync(new URL('../src/views/knowledge/KnowledgeManagementView.vue', import.meta.url), 'utf8')
  const descriptor = parse(source).descriptor
  const script = compileScript(descriptor, {id: 'knowledge-render', inlineTemplate: true}).content
  const compiled = ts.transpileModule(script, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText
  const module = {exports: {}}
  const deps = {vue: Vue, 'element-plus': {ElMessageBox: {confirm: async () => true}},
    '@/stores/auth': {useAuthStore: () => ({user: {role}})}, '@/api/knowledge': {}}
  vm.runInNewContext(compiled, {module, exports: module.exports, require: key => deps[key], crypto: {randomUUID: () => 'render-only'}})
  const app = Vue.createSSRApp(module.exports.default)
  // Render the real compiled SFC; UI library stubs avoid DOM/browser assumptions.
  for (const name of new Set([...source.matchAll(/<(el-[a-z-]+)/g)].map(match => match[1]))) {
    app.component(name, {props: ['title', 'description', 'label', 'data'], setup(props, {slots}) {
      return () => Vue.h('div', {'data-ui': name}, name === 'el-table' ? '暂无数据' : [props.title || props.description || props.label || '', slots.default?.()])
    }})
  }
  return renderToString(app)
}

test('compiled knowledge component renders all panels and initial empty state', async () => {
  const html = await render('ADMIN')
  for (const label of ['知识库管理', '文档管理', 'Chunk预览', '索引管理', '评测中心', '尚无知识库']) assert.ok(html.includes(label))
  assert.ok(html.includes('不代表真实模型效果'))
})

test('compiled component renders insufficient-permission state for a viewer', async () => {
  assert.ok((await render('VIEWER')).includes('知识治理管理需要管理员权限'))
})
