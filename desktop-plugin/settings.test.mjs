// node --test desktop-plugin/settings.test.mjs (WSL only)
import { registerHooks } from 'node:module'
import assert from 'node:assert/strict'
import test from 'node:test'
const states = []
globalThis.__settingsStates = states
globalThis.__settingsHost = { composer: {}, state: { focusedSessionId: { get: () => 's1' } }, request: async () => ({ protocol: 1, image_mode: 'vision_analyze_reference' }) }
const stubs = {
  '@hermes/plugin-sdk': 'export const COMPOSER_AREAS={};export const KEYBINDS_AREA="keys";export const PALETTE_AREA="palette";export const host=globalThis.__settingsHost;',
  react: 'export const useState=v=>[v,x=>globalThis.__settingsStates.push(x)];export const useEffect=()=>{};',
  'react/jsx-runtime': 'export const jsx=(t,p)=>({t,p});export const jsxs=(t,p)=>({t,p});'
}
registerHooks({
  resolve(s, c, next) { return stubs[s] ? { url: 'stub:' + s, shortCircuit: true } : next(s, c) },
  load(u, c, next) { return u.startsWith('stub:') ? { format: 'module', source: stubs[u.slice(5)], shortCircuit: true } : next(u, c) }
})
const mod = await import('./neo-composer/plugin.js')

test('control client checks only on request and requires explicit install action', async () => {
  const calls = []
  const client = mod.createHostAdapterClient({ settings: () => ({ url: 'http://127.0.0.1:3460/', token: 'prediction', controlToken: 'control' }),
    fetchImpl: async (url, init) => { calls.push([url, init]); return { ok: true, json: async () => ({ backend: { source_applied: true }, frontend: { rebuild_required: true } }) } } })
  assert.equal(calls.length, 0)
  await client.run('check')
  assert.equal(calls[0][1].method, 'GET')
  assert.equal(calls[0][1].headers.Authorization, 'Bearer control')
  await client.run('install')
  assert.equal(calls[1][0], 'http://127.0.0.1:3460/v1/host-adapter/install')
  assert.deepEqual(JSON.parse(calls[1][1].body), { confirm: true })
  assert.equal(calls[1][1].method, 'POST')
})

test('control client rejects remote URLs, missing tokens and unknown actions without network', async () => {
  for (const url of ['https://example.com', 'http://127.0.0.1.evil:3460', 'http://user:pass@localhost:3460', 'file:///tmp/x', 'http://localhost:3460/command']) {
    const c = mod.createHostAdapterClient({ settings: () => ({ url, token: 'secret' }), fetchImpl: () => assert.fail('network') })
    await assert.rejects(c.run('install'), /loopback|本機/)
  }
  const c = mod.createHostAdapterClient({ settings: () => ({ url: 'http://localhost:3460' }), fetchImpl: () => assert.fail('network') })
  await assert.rejects(c.run('check'), /Token|token/)
  await assert.rejects(c.run('command'), /action/)
})

test('source status never advertises runtime enabled; runtime needs SDK and contract-1 RPC', async () => {
  const pending = { backend: { source_applied: true }, frontend: { state: 'rebuild_required', rebuild_required: true } }
  assert.match(mod.describeHostAdapter(pending), /原始碼/)
  assert.match(mod.describeHostAdapter(pending), /WSL|重建/)
  assert.doesNotMatch(mod.describeHostAdapter(pending), /已啟用/)
  const h = globalThis.__settingsHost
  assert.equal((await mod.probeHostAdapter(h)).sdk, false)
  h.composer.steerStrict = () => {}
  assert.equal((await mod.probeHostAdapter(h)).backend, true)
  h.request = async () => ({ protocol: 2 })
  assert.equal((await mod.probeHostAdapter(h)).backend, false)
})

test('settings exposes check/install/rollback, and mount does not install', async () => {
  const calls = []
  globalThis.fetch = async (url, init) => { calls.push([url, init]); return { ok: true, json: async () => ({ backend: { source_applied: true }, frontend: { state: 'rebuild_required' } }) } }
  const tree = mod.HostAdapterSettings({ settings: { url: 'http://localhost:3460', token: 'token' } })
  const nodes = []
  const walk = n => { if (n && typeof n === 'object') { nodes.push(n); for (const v of Object.values(n.p || {})) (Array.isArray(v) ? v : [v]).forEach(x => { if (x && typeof x === 'object') walk(x) }) } }
  walk(tree)
  const buttons = nodes.filter(n => n.t === 'button')
  assert.deepEqual(buttons.map(n => n.p.children), ['檢查主機介面', '安裝主機 Adapter', '回復上次安裝'])
  assert.equal(calls.length, 0)
  await buttons[1].p.onClick()
  assert.match(calls[0][0], /host-adapter\/install$/)
  assert.ok(states.some(s => typeof s === 'string' && /原始碼/.test(s)))
})
