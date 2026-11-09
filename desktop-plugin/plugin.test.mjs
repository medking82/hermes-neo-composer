// node --test desktop-plugin/plugin.test.mjs   (Node >= 22.15 for module.registerHooks)
import { registerHooks } from 'node:module'
import assert from 'node:assert/strict'
import test from 'node:test'

const stubs = {
  '@hermes/plugin-sdk': 'export const COMPOSER_AREAS={underside:"composer.underside"};export const KEYBINDS_AREA="keybinds";export const PALETTE_AREA="palette";export const host=globalThis.__host;export const writeClipboardText=async()=>{};',
  react: 'export const useState=v=>[v,()=>{}];export const useEffect=()=>{};',
  'react/jsx-runtime': 'export const jsx=(t,p)=>({t,p});export const jsxs=(t,p)=>({t,p});'
}
registerHooks({
  resolve(spec, ctx, next) { return stubs[spec] ? { url: 'stub:' + spec, shortCircuit: true } : next(spec, ctx) },
  load(url, ctx, next) {
    return url.startsWith('stub:') ? { format: 'module', source: stubs[url.slice(5)], shortCircuit: true } : next(url, ctx)
  }
})

function atom(v) {
  const ls = new Set()
  return { get: () => v, set(n) { v = n; for (const l of ls) l(v) }, listen(f) { ls.add(f); return () => ls.delete(f) } }
}
const calls = { history: 0, suggest: [], draft: [] }
globalThis.__host = {
  state: { focusedSessionId: atom('s1'), busyBySession: atom({}) },
  request: async (m, p) => { calls.history++; return { messages: [{ role: 'user', text: 'q' }, { role: 'tool', text: 'x' }, { role: 'assistant', text: 'a' }] } },
  composer: { setDraft: async (sid, t) => { calls.draft.push(t); return true }, focus() {} },
  notify() {}
}
globalThis.fetch = async (url, init) => {
  calls.suggest.push({ url, body: JSON.parse(init.body), auth: init.headers.Authorization })
  return { ok: true, status: 200, json: async () => ({ suggestion: '下一步', status: 'ready' }) }
}

const mod = await import('./neo-composer/plugin.js')

test('toServiceMessages keeps user/assistant text only', () => {
  assert.deepEqual(mod.toServiceMessages({ messages: [{ role: 'tool', text: 't' }, { role: 'user', text: ' hi ' }, { role: 'assistant', content: 'yo' }, { role: 'assistant', text: '' }] }),
    [{ role: 'user', content: ' hi ' }, { role: 'assistant', content: 'yo' }])
})

test('controller fetches and honours settings/token', async () => {
  const store = new Map([['settings', { url: 'http://h:1/', token: 'tk' }]])
  const c = mod.createController({ fetchImpl: globalThis.fetch, request: globalThis.__host.request, storage: { get: k => store.get(k) } })
  await c.refresh('s1')
  assert.equal(c.get().suggestion, '下一步')
  const last = calls.suggest.at(-1)
  assert.equal(last.url, 'http://h:1/v1/suggest')
  assert.equal(last.auth, 'Bearer tk')
  assert.deepEqual(last.body.messages.map(m => m.role), ['user', 'assistant'])
})

test('controller skips when last message is user, and when disabled', async () => {
  const n = calls.suggest.length
  const c = mod.createController({ fetchImpl: globalThis.fetch, request: async () => ({ messages: [{ role: 'user', text: 'q' }] }), storage: { get: () => ({}) } })
  await c.refresh('s1')
  assert.equal(c.get().status, 'idle')
  const d = mod.createController({ fetchImpl: globalThis.fetch, request: globalThis.__host.request, storage: { get: () => ({ enabled: false }) } })
  await d.refresh('s1')
  assert.equal(calls.suggest.length, n)
})

test('stale responses are dropped', async () => {
  let release
  const slow = () => new Promise(r => { release = r })
  const c = mod.createController({ fetchImpl: async () => { await slow(); return { ok: true, json: async () => ({ suggestion: 'old' }) } }, request: globalThis.__host.request, storage: { get: () => ({}) } })
  const p = c.refresh('s1')
  await new Promise(r => setTimeout(r, 5))
  c.clear()
  release(); await p
  assert.equal(c.get().suggestion, null)
})

test('service errors surface as status=error, not throw', async () => {
  const c = mod.createController({ fetchImpl: async () => { throw new Error('ECONNREFUSED') }, request: globalThis.__host.request, storage: { get: () => ({}) } })
  await c.refresh('s1')
  assert.equal(c.get().status, 'error')
})

test('register wires underside pill, keybind, palette; busy clears and idle refetches', async () => {
  const regs = []; let disposer
  const copied = []
  const ctx = { os: { writeClipboard: async text => { copied.push(text); return true } }, storage: { get: () => ({}), set() {} }, registerMany: r => regs.push(...r), registerSettingsPage() {}, onDispose: f => { disposer = f } }
  mod.default.register(ctx)
  assert.deepEqual(regs.map(r => r.area), ['composer.underside', 'keybinds', 'palette'])
  const h = globalThis.__host
  const before = calls.history
  h.state.busyBySession.set({ s1: true })
  h.state.busyBySession.set({ s1: false })
  await new Promise(r => setTimeout(r, 10))
  assert.ok(calls.history > before)
  const pill = regs.find(r => r.area === 'composer.underside').render()
  assert.equal(await pill.p.copy('下一步'), true)
  assert.deepEqual(copied, ['下一步'])
  const accept = regs.find(r => r.area === 'keybinds').data.run
  const n = calls.draft.length
  h.composer.getDraft = async () => 'existing user draft'
  assert.equal(await accept(), false)
  assert.equal(calls.draft.length, n)
  h.composer.getDraft = async () => { h.state.focusedSessionId.set('s2'); return '' }
  assert.equal(await accept(), false)
  assert.equal(calls.draft.length, n)
  h.state.focusedSessionId.set('s1')
  await new Promise(r => setTimeout(r, 10))
  h.composer.getDraft = async () => ''
  assert.equal(await accept(), true)
  assert.equal(calls.draft.at(-1), '下一步')
  disposer()
})

test('isEditorEmpty', () => {
  assert.equal(mod.isEditorEmpty({ hasAttribute: () => false, textContent: ' ​ ' }), true)
  assert.equal(mod.isEditorEmpty({ hasAttribute: () => false, textContent: 'x' }), false)
})
