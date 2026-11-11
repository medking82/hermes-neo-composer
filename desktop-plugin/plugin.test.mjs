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

test('Hermes mode uses bounded host RPC without service credentials or HTTP fallback', async () => {
  const calls = []
  const c = mod.createController({
    fetchImpl: () => assert.fail('Hermes mode must not call service'),
    storage: { get: () => ({ backend: 'hermes', token: 'private' }) },
    request: async (method, params) => {
      calls.push([method, params])
      if (method === 'session.history') return { messages: Array.from({ length: 20 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', text: 'x'.repeat(5000) })) }
      return { suggestion: '下一步', status: 'ready' }
    }
  })
  await c.refresh('s1')
  assert.equal(c.get().suggestion, '下一步')
  assert.equal(calls[1][0], 'plugin.neo-composer.predict')
  assert.equal(calls[1][1].messages.length, 8)
  assert.equal(calls[1][1].messages[0].content.length, 2800)
  assert.deepEqual(Object.keys(calls[1][1]).sort(), ['messages', 'session_id'])
})

test('Hermes mode fails closed on cross-profile and unavailable backend', async () => {
  const make = context => mod.createController({ context,
    fetchImpl: () => assert.fail('no silent service fallback'),
    storage: { get: () => ({ backend: 'hermes' }) },
    request: async method => {
      if (method === 'session.history') return [{ role: 'assistant', text: 'done' }]
      throw new Error('RPC not installed')
    }
  })
  const cross = make(() => ({ profile: 'bot', gatewayProfile: 'default' }))
  await cross.refresh('s1')
  assert.match(cross.get().error, /profile/)
  const missing = make(() => ({}))
  await missing.refresh('s1')
  assert.match(missing.get().error, /RPC not installed/)
})

test('Hermes results are discarded after profile or backend changes', async () => {
  for (const kind of ['profile', 'backend']) {
    let release, profile = 'default', backend = 'hermes'
    const c = mod.createController({
      context: () => ({ profile, gatewayProfile: profile }),
      storage: { get: () => ({ backend }) },
      request: async method => method === 'session.history' ? [{ role: 'assistant', text: 'done' }]
        : new Promise(resolve => { release = resolve }),
      fetchImpl: () => assert.fail('network')
    })
    const pending = c.refresh('s1')
    await new Promise(resolve => setImmediate(resolve))
    if (kind === 'profile') profile = 'other'; else backend = 'service'
    release({ suggestion: 'stale', status: 'ready' })
    await pending
    assert.equal(c.get().suggestion, null)
  }
})

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
  // Filling hides the pill but keeps the suggestion so an emptied draft brings it back.
  const ctrl = pill.p.ctrl
  assert.equal(ctrl.get().suggestion, '下一步')
  assert.equal(ctrl.get().filled, true)
  ctrl.setFilled(false)
  assert.equal(ctrl.get().filled, false)
  ctrl.clear()
  assert.equal(ctrl.get().suggestion, null)
  disposer()
})

test('isEditorEmpty', () => {
  assert.equal(mod.isEditorEmpty({ hasAttribute: () => false, textContent: ' ​ ' }), true)
  assert.equal(mod.isEditorEmpty({ hasAttribute: () => false, textContent: 'x' }), false)
})

test('chord matching: ctrl+enter only; shift+enter and plain enter untouched', () => {
  const ev = o => ({ key: 'Enter', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...o })
  assert.equal(mod.matchesChord(ev({ ctrlKey: true }), 'ctrl+enter'), true)
  assert.equal(mod.matchesChord(ev({}), 'ctrl+enter'), false)
  assert.equal(mod.matchesChord(ev({ shiftKey: true }), 'ctrl+enter'), false)
  assert.equal(mod.matchesChord(ev({ ctrlKey: true, shiftKey: true }), 'ctrl+enter'), false)
  assert.equal(mod.matchesChord(ev({ ctrlKey: true, isComposing: true }), 'ctrl+enter'), false)
  assert.equal(mod.matchesChord(ev({ altKey: true }), 'alt+enter'), true)
})

function steerHost(composer) {
  const notes = []
  return { notes, host: { state: { focusedSessionId: atom('s1'), busyBySession: atom({ s1: true }) }, notify: n => notes.push(n), composer } }
}

test('steer without host seam fails closed: no queue, no submit, no draft write', async () => {
  const calls2 = []
  const { host, notes } = steerHost({ submit: () => calls2.push('submit'), setDraft: () => calls2.push('setDraft') })
  const r = await mod.createSteerKey({ host, settings: () => ({ steerKey: 'ctrl+enter' }) }).steer('s1')
  assert.equal(r.status, 'unsupported')
  assert.deepEqual(calls2, [])
  assert.equal(notes[0].kind, 'warning')
})

test('steer separates accepted from delivered and never queues on rejection', async () => {
  for (const [res, text] of [[{ status: 'accepted', delivered: false }, '尚未送達'], [{ status: 'accepted', delivered: true }, '安全邊界'], [{ status: 'rejected', delivered: false }, '被拒絕']]) {
    const { host, notes } = steerHost({ steerStrict: async () => res, submit: () => assert.fail('must not queue') })
    const r = await mod.createSteerKey({ host, settings: () => ({ steerKey: 'ctrl+enter' }) }).steer('s1')
    assert.equal(r.status, res.status)
    assert.match(notes[0].message, new RegExp(text))
  }
})

test('steer understands host contract-1 receipts and keeps the draft on anything but delivered', async () => {
  for (const [res, text] of [[{ status: 'delivered' }, '安全邊界'], [{ status: 'not_delivered', reason: 'boundary_timeout' }, 'boundary_timeout'], [{ status: 'unknown' }, '未送達'], [{ status: 'idle' }, '沒有執行中']]) {
    const { host, notes } = steerHost({ steerStrict: async () => res, submit: () => assert.fail('must not queue') })
    const r = await mod.createSteerKey({ host, settings: () => ({ steerKey: 'ctrl+enter' }) }).steer('s1')
    assert.equal(r.status, res.status)
    assert.match(notes[0].message, new RegExp(text))
  }
})

test('steer is ignored when idle and a throwing seam keeps the draft', async () => {
  const idle = steerHost({ steerStrict: async () => assert.fail('idle') })
  idle.host.state.busyBySession.set({})
  assert.equal((await mod.createSteerKey({ host: idle.host, settings: () => ({}) }).steer('s1')).status, 'idle')
  const bad = steerHost({ steerStrict: async () => { throw new Error('boom') } })
  assert.equal((await mod.createSteerKey({ host: bad.host, settings: () => ({}) }).steer('s1')).status, 'error')
})

test('Enter-queues sets session-scoped busy=queue once per session', async () => {
  const reqs = []
  const host = { request: async (m, p) => { reqs.push([m, p]) } }
  const done = new Set()
  assert.equal(await mod.ensureQueueMode(host, 's1', done), true)
  assert.equal(await mod.ensureQueueMode(host, 's1', done), false)
  assert.deepEqual(reqs, [['config.set', { session_id: 's1', key: 'busy', value: 'queue' }]])
})
