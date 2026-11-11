import { registerHooks } from 'node:module'
import test from 'node:test'
import assert from 'node:assert/strict'

function atom(value) {
  const listeners = new Set()
  return { get: () => value, set(next) { value = next; for (const fn of listeners) fn(next) },
    listen(fn) { listeners.add(fn); return () => listeners.delete(fn) }, count: () => listeners.size }
}
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const tick = () => new Promise(resolve => setImmediate(resolve))
async function settle(c) { for (let i = 0; i < 100 && c.view.get().loading; i++) await tick(); assert.equal(c.view.get().loading, false) }
function fixture() {
  const settings = { enabled: true, revision: 0 }
  const state = { focusedSessionId: atom('a'), focusedStoredSessionId: atom('stored-a'),
    focusedSessionProfile: atom('default'), profile: atom('default'), gateway: atom('connected'), busyBySession: atom({}) }
  const calls = [], writes = [], notices = [], contributions = [], disposers = [], events = new Map()
  let generation = null, readDraft = null, settingsRead = null, capability = true, draft = '', token = 0
  const api = { state, notify: n => notices.push(n), async request(method, params) {
    calls.push([method, params])
    if (method === 'runtime.describe') return { capabilities: capability ? ['plugin-rpc-v1'] : [] }
    if (method === 'session.history') return { messages: [{ role: 'tool', text: 'ignore' },
      { role: 'user', text: 'Please shorten this report' }, { role: 'assistant', text: 'Report ready' }] }
    if (method === 'plugin.neo-composer.suggest') return generation ? generation(params) : { text: 'Use a table', token: params.token }
    throw new Error('Unexpected RPC: ' + method)
  }, composer: {
    getDraft: async () => readDraft ? readDraft() : draft,
    async insertText(id, text, options) {
      assert.equal(options.mode, 'inline'); draft += text; writes.push([id, text]); return true
    }, focus(id) { calls.push(['focus', id]) }
  } }
  const ctx = {
    async rest(path, options) {
      calls.push([path, options?.body])
      if (path === '/settings') {
        if (options?.method === 'POST') { settings.enabled = options.body.enabled; settings.revision++ }
        return settingsRead ? settingsRead() : { ...settings }
      }
      if (path === '/prepare') return { status: 'pending', token: String(++token) }
      if (path === '/dismiss' || path === '/invalidate') return { ok: true }
      throw new Error('Unexpected REST: ' + path)
    },
    onDispose(fn) { disposers.push(fn) }, onEvent(name, fn) { events.set(name, fn); return () => events.delete(name) },
    register(c) { contributions.push(c) }, registerSettingsPage(c) { contributions.push(c) },
    os: { async writeClipboard(text) { calls.push(['clipboard', text]); return true } }
  }
  return { api, ctx, state, settings, calls, writes, notices, contributions,
    generation(fn) { generation = fn }, draft(text) { draft = text }, readDraft(fn) { readDraft = fn },
    settingsRead(fn) { settingsRead = fn }, capability(value) { capability = value }, dispose() { disposers.forEach(fn => fn()) } }
}
globalThis.__catalogAtom = atom
const seed = fixture()
globalThis.__catalogHost = seed.api
registerHooks({ resolve(specifier, context, next) {
  const sources = {
    '@hermes/plugin-sdk': 'export const atom=globalThis.__catalogAtom; export const host=globalThis.__catalogHost; export const useValue=a=>a.get(); export const Button="button"; export const COMPOSER_AREAS={underside:"composer.underside"}; export const KEYBINDS_AREA="keybinds"; export const PALETTE_AREA="palette";',
    'react/jsx-runtime': 'export const jsx=(type,props,key)=>({type,props,key});'
  }
  return specifier in sources ? { url: 'data:text/javascript,' + encodeURIComponent(sources[specifier]), shortCircuit: true } : next(specifier, context)
} })
const { createController, default: plugin } = await import('../desktop/plugin.js')

for (const [label, draft] of [['typed text', 'my draft'], ['whitespace', '  '], ['unavailable editor', null]]) {
  test('accept preserves ' + label, async () => {
    const f = fixture(), c = createController(f.ctx, f.api)
    await settle(c); f.draft(draft); await c.accept()
    assert.deepEqual(f.writes, []); assert.equal(c.view.get().text, 'Use a table'); f.dispose()
  })
}
test('accept addresses the captured runtime session and dismisses durable candidate', async () => {
  const f = fixture(), c = createController(f.ctx, f.api)
  await settle(c); await c.accept()
  assert.deepEqual(f.writes, [['a', 'Use a table']]); assert.equal(c.view.get().text, '')
  assert(f.calls.some(([path, body]) => path === '/dismiss' && body.session_id === 'stored-a'))
  const rpc = f.calls.find(([method]) => method === 'plugin.neo-composer.suggest')[1]
  assert.equal(rpc.session_id, 'a'); assert.equal(rpc.stored_session_id, 'stored-a')
  assert(rpc.messages.every(row => row.role !== 'tool')); f.dispose()
})
test('typing between draft read and insert remains in the editor', async () => {
  const f = fixture(), c = createController(f.ctx, f.api)
  await settle(c)
  f.readDraft(() => { f.draft('new typing '); return '' })
  await c.accept()
  f.readDraft(null)
  assert.equal(await f.api.composer.getDraft(), 'new typing Use a table')
  f.dispose()
})
test('concurrent accept actions insert a candidate only once', async () => {
  const f = fixture(), c = createController(f.ctx, f.api)
  await settle(c)
  await Promise.all([c.accept(), c.accept()])
  assert.equal(f.writes.length, 1)
  f.dispose()
})
test('new generation waits for the previous turn invalidation', async () => {
  const f = fixture(), c = createController(f.ctx, f.api)
  await settle(c)
  const d = deferred(), rest = f.ctx.rest
  f.ctx.rest = (path, opts) => path === '/invalidate' ? d.promise : rest(path, opts)
  const before = f.calls.filter(([method]) => method === '/prepare').length
  f.state.busyBySession.set({ a: true })
  f.state.busyBySession.set({ a: false })
  await tick()
  assert.equal(f.calls.filter(([method]) => method === '/prepare').length, before)
  d.resolve({ ok: true }); await settle(c)
  assert.equal(f.calls.filter(([method]) => method === '/prepare').length, before + 1)
  f.dispose()
})
test('late generation is dropped after busy to idle even with the same session', async () => {
  const f = fixture(), d = deferred(); let count = 0
  f.generation(async params => ++count === 1 ? d.promise : { text: 'New candidate', token: params.token })
  const c = createController(f.ctx, f.api)
  while (count === 0) await tick()
  f.state.busyBySession.set({ a: true }); assert.equal(c.view.get().text, '')
  f.state.busyBySession.set({ a: false }); await settle(c)
  d.resolve({ text: 'Old candidate', token: 'old' }); await tick()
  assert.equal(c.view.get().text, 'New candidate')
  assert(f.calls.some(([path]) => path === '/invalidate')); f.dispose()
})
test('session switch during generation cannot publish to the new session', async () => {
  const f = fixture(), d = deferred(); let started = false
  f.generation(params => { if (params.session_id === 'a') { started = true; return d.promise }; return { text: 'Session B', token: params.token } })
  const c = createController(f.ctx, f.api)
  while (!started) await tick()
  f.state.focusedStoredSessionId.set('stored-b'); f.state.focusedSessionId.set('b'); await settle(c)
  d.resolve({ text: 'Session A', token: 'old' }); await tick()
  assert.equal(c.view.get().text, 'Session B'); f.dispose()
})
test('disable and re-enable during generation invalidates the returned revision', async () => {
  const f = fixture(), d = deferred(); let started = false
  f.generation(() => { started = true; return d.promise })
  const c = createController(f.ctx, f.api)
  while (!started) await tick()
  f.settings.revision += 2
  d.resolve({ text: 'Stale', token: 'old' }); await settle(c)
  assert.equal(c.view.get().text, ''); assert.match(c.view.get().status, /Settings changed/); f.dispose()
})
test('focus change while reading draft prevents a write', async () => {
  const f = fixture(), c = createController(f.ctx, f.api)
  await settle(c)
  const d = deferred(); let reading = false
  f.readDraft(() => { reading = true; return d.promise })
  const accepting = c.accept()
  while (!reading) await tick()
  f.state.busyBySession.set({ a: true })
  d.resolve(''); await accepting
  assert.deepEqual(f.writes, []); f.dispose()
})
test('disabled settings prevent generation and acceptance', async () => {
  const f = fixture(), c = createController(f.ctx, f.api)
  await settle(c); f.settings.enabled = false; await c.accept()
  assert.deepEqual(f.writes, [])
  const before = f.calls.length; await c.refresh(true)
  assert(!f.calls.slice(before).some(([method]) => method === 'plugin.neo-composer.suggest'))
  assert.equal(c.view.get().text, ''); f.dispose()
})
test('profile mismatch fails closed before REST or generation', async () => {
  const f = fixture(); f.state.focusedSessionProfile.set('other')
  const c = createController(f.ctx, f.api); await settle(c)
  assert.equal(f.calls.length, 0); assert.match(c.view.get().status, /profile/); f.dispose()
})
test('missing plugin RPC capability is a visible limitation', async () => {
  const f = fixture(); f.capability(false)
  const c = createController(f.ctx, f.api); await settle(c)
  assert(!f.calls.some(([method]) => method === 'plugin.neo-composer.suggest'))
  assert.match(c.view.get().status, /does not expose plugin RPC/); f.dispose()
})
test('copy and dismiss use public clipboard and token APIs', async () => {
  const f = fixture(), c = createController(f.ctx, f.api); await settle(c)
  await c.copy(); assert(f.calls.some(([method, text]) => method === 'clipboard' && text === 'Use a table'))
  await c.dismiss(); assert.equal(c.view.get().text, '')
  assert(f.calls.some(([method]) => method === '/dismiss')); f.dispose()
})
test('explicit refresh replaces a candidate; unload drops in-flight work and subscriptions', async () => {
  const f = fixture(), c = createController(f.ctx, f.api); await settle(c)
  const d = deferred(); f.generation(() => d.promise)
  const refreshing = c.refresh(true)
  while (!f.calls.some(([path, body]) => path === '/prepare' && body.refresh)) await tick()
  f.dispose(); d.resolve({ text: 'After unload', token: 'x' }); await refreshing
  assert.equal(c.view.get().text, '')
  assert.equal(f.state.focusedSessionId.count(), 0)
})
test('default plugin registers underside, settings, palette and an unbound accept action', async () => {
  plugin.register(seed.ctx)
  await tick()
  assert.equal(plugin.defaultEnabled, false)
  assert(seed.contributions.some(c => c.area === 'composer.underside'))
  const keybind = seed.contributions.find(c => c.area === 'keybinds')
  assert.deepEqual(keybind.data.defaults, [])
  assert(seed.contributions.some(c => c.area === 'palette'))
  seed.dispose()
})
