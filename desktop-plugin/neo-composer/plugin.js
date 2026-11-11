// Neo Composer v0.5 — ghost-text next-prompt suggestions for Hermes Desktop.
//
// Durability contract: only `@hermes/plugin-sdk` public surface + the standalone
// neo-suggest HTTP service. Suggestions need no Hermes core patch; strict steering
// uses the optional, capability-checked host adapter installed from settings.
//   * stable path  : COMPOSER_AREAS.underside pill (click = fill composer, copy button)
//   * enhancer     : in-box ghost text via the composer's placeholder attribute and
//                    Tab-to-accept. It is feature-detected; if a Hermes update
//                    renames the editor slot, the enhancer silently turns off and
//                    the pill keeps working.
import { COMPOSER_AREAS, KEYBINDS_AREA, PALETTE_AREA, host } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

export const VERSION = '0.5.1'
export const EDITOR_SELECTOR = "[data-slot='composer-rich-input']"
export const DEFAULTS = { backend: 'service', url: 'http://127.0.0.1:3460', token: '', controlToken: '', enabled: true, inline: true, steerKey: 'ctrl+enter', enterQueues: true }
const ORIGINAL = 'data-neo-original-placeholder'

// ------------------------------------------------------------------ pure helpers

export function toServiceMessages(history) {
  const rows = Array.isArray(history?.messages) ? history.messages : Array.isArray(history) ? history : []
  const out = []
  for (const m of rows) {
    if (!m || (m.role !== 'user' && m.role !== 'assistant')) continue
    const text = typeof m.text === 'string' ? m.text : typeof m.content === 'string' ? m.content : ''
    if (text.trim()) out.push({ role: m.role, content: text })
  }
  return out.slice(-40)
}

export function isEditorEmpty(el) {
  if (!el) return false
  if (el.hasAttribute?.('data-empty')) return true
  return (el.textContent || '').replace(/\u200b/g, '').trim() === ''
}

export function createController({ fetchImpl, request, storage, context = () => ({}), now = () => Date.now() }) {
  const listeners = new Set()
  let state = { sessionId: null, suggestion: null, status: 'idle', error: null, filled: false }
  let seq = 0
  const settings = () => ({ ...DEFAULTS, ...(storage?.get('settings', {}) || {}) })
  const set = patch => {
    state = { ...state, ...patch }
    for (const fn of listeners) fn(state)
  }

  async function refresh(sessionId) {
    const s = settings()
    const my = ++seq
    const identity = JSON.stringify(context())
    const current = () => my === seq && identity === JSON.stringify(context()) && s.backend === settings().backend
    if (!s.enabled || !sessionId) return set({ sessionId, suggestion: null, status: 'idle', filled: false })
    set({ sessionId, suggestion: null, status: 'loading', error: null, filled: false })
    try {
      const address = context()
      if (s.backend === 'hermes' && address.profile !== address.gatewayProfile) {
        throw new Error('請切換到此工作階段的 Hermes profile 再產生建議')
      }
      const history = await request('session.history', { session_id: sessionId })
      const messages = toServiceMessages(history)
      if (!current()) return
      if (!messages.length || messages[messages.length - 1].role !== 'assistant') {
        return set({ status: 'idle' })
      }
      let body
      if (s.backend === 'hermes') {
        // Host resolves auxiliary.neo_composer and owns all provider credentials.
        body = await request('plugin.neo-composer.predict', {
          session_id: sessionId,
          messages: messages.slice(-8).map(row => ({ ...row, content: row.content.slice(-2800) }))
        })
      } else {
        const headers = { 'Content-Type': 'application/json' }
        if (s.token) headers.Authorization = `Bearer ${s.token}`
        const resp = await fetchImpl(`${s.url.replace(/\/$/, '')}/v1/suggest`, {
          method: 'POST', headers, body: JSON.stringify({ messages, client: `hermes-desktop/${VERSION}` })
        })
        body = await resp.json().catch(() => ({}))
        if (!current()) return
        if (!resp.ok) return set({ status: 'error', error: body.error || `HTTP ${resp.status}` })
      }
      if (!current()) return
      set({ suggestion: body.suggestion || null, status: body.suggestion ? 'ready' : body.status || 'empty', at: now() })
    } catch (err) {
      if (current()) set({ status: 'error', error: String(err?.message || err) })
    }
  }

  return {
    get: () => state,
    settings,
    subscribe(fn) { listeners.add(fn); fn(state); return () => listeners.delete(fn) },
    refresh,
    clear() { seq++; set({ suggestion: null, status: 'idle', filled: false }) },
    // Filled into the composer: hide the pill but keep the suggestion, so clearing the draft brings it back.
    setFilled(filled) { if (state.filled !== !!filled) set({ filled: !!filled }) }
  }
}

// ------------------------------------------------------------------ in-box ghost text (enhancer)

function visibleEditors() {
  if (typeof document === 'undefined') return []
  return [...document.querySelectorAll(EDITOR_SELECTOR)].filter(el => !el.closest('[data-pane-hidden]'))
}

function installInline(ctrl, accept) {
  if (typeof document === 'undefined' || typeof MutationObserver === 'undefined') return () => {}
  let applying = false
  const paint = () => {
    const { suggestion } = ctrl.get()
    const on = ctrl.settings().inline && suggestion
    applying = true
    const editors = visibleEditors()
    for (const el of editors) {
      if (!el.hasAttribute(ORIGINAL)) el.setAttribute(ORIGINAL, el.getAttribute('data-placeholder') || '')
      const want = on && editors.length === 1 ? `${suggestion}   ⇥ Tab` : el.getAttribute(ORIGINAL)
      if (el.getAttribute('data-placeholder') !== want) el.setAttribute('data-placeholder', want)
      if (!on) el.removeAttribute(ORIGINAL)
    }
    applying = false
  }
  // React re-renders reset data-placeholder; re-apply after them.
  const restore = () => {
    const eds = visibleEditors()
    if (ctrl.get().filled && eds.length === 1 && isEditorEmpty(eds[0])) ctrl.setFilled(false)
  }
  const mo = new MutationObserver(() => { if (!applying) { paint(); restore() } })
  mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['data-placeholder', 'data-empty'] })
  const onKey = ev => {
    if (ev.key !== 'Tab' || ev.shiftKey || ev.ctrlKey || ev.metaKey || ev.altKey || ev.isComposing) return
    const el = ev.target?.closest?.(EDITOR_SELECTOR)
    if (!el || !ctrl.settings().inline || !ctrl.get().suggestion || !isEditorEmpty(el)) return
    ev.preventDefault()
    ev.stopPropagation()
    void accept()
  }
  document.addEventListener('keydown', onKey, true)
  const unsub = ctrl.subscribe(paint)
  return () => {
    unsub(); mo.disconnect(); document.removeEventListener('keydown', onKey, true)
    applying = true
    for (const el of document.querySelectorAll(`[${ORIGINAL}]`)) {
      el.setAttribute('data-placeholder', el.getAttribute(ORIGINAL)); el.removeAttribute(ORIGINAL)
    }
  }
}


// ------------------------------------------------------------------ busy keyboard (Enter queues, chord steers)
// Public-SDK only. Hermes core's own Ctrl+Enter *queues*; this plugin takes over that chord in capture phase
// (same technique as Tab above) and NEVER falls back to queue/interrupt/redirect: if the host lacks the strict
// steer seam (`host.composer.steerStrict`) the draft and attachments are left untouched and the user is told.
// Seam contract (not in the current public SDK, see docs/busy-keyboard.md):
//   steerStrict(sessionId) -> { status: 'accepted'|'rejected'|'unsupported', delivered: boolean, turnId?: string }
// `accepted` = the targeted turn buffered it; only `delivered: true` (safe-boundary receipt) may clear the draft,
// and clearing is the seam's job, never ours.
export function parseChord(chord) {
  const parts = String(chord || '').toLowerCase().split('+').map(x => x.trim()).filter(Boolean)
  const key = parts.pop() || ''
  const mods = new Set(parts)
  return { key, ctrl: mods.has('ctrl') || mods.has('mod'), meta: mods.has('meta'), alt: mods.has('alt'), shift: mods.has('shift') }
}

export function matchesChord(ev, chord) {
  const c = parseChord(chord)
  if (!c.key || ev.isComposing) return false
  return String(ev.key).toLowerCase() === c.key && !!ev.ctrlKey === c.ctrl && !!ev.metaKey === c.meta
    && !!ev.altKey === c.alt && !!ev.shiftKey === c.shift
}

export function createSteerKey({ host, settings }) {
  const notify = (kind, message) => host.notify?.({ kind, message })
  async function steer(sessionId) {
    if (!sessionId || !(host.state.busyBySession.get() || {})[sessionId]) return { status: 'idle' }
    if (typeof host.composer?.steerStrict !== 'function') {
      notify('warning', '此 Hermes 版本沒有嚴格 steer 介面：草稿與圖片已保留，未排隊也未中斷')
      return { status: 'unsupported' }
    }
    let r
    try { r = await host.composer.steerStrict(sessionId) } catch (err) {
      notify('error', `Steer 失敗，草稿已保留：${String(err?.message || err)}`)
      return { status: 'error' }
    }
    // Host contract 1 receipt: 'delivered' (matching request/generation/image_count receipt; the host already cleared
    // the draft). Legacy-shaped { status:'accepted', delivered:true } is honoured too. Everything else keeps the draft.
    const delivered = r?.status === 'delivered' || (r?.status === 'accepted' && r.delivered === true)
    if (delivered) notify('info', '已在安全邊界送達（模型是否已讀取未確認）')
    else if (r?.status === 'accepted') notify('info', '已被該回合接受，尚未送達；草稿保留至收到回執')
    else if (r?.status === 'idle') notify('info', '該工作階段目前沒有執行中的回合，草稿已保留')
    else notify('warning', r?.status === 'unsupported' ? '主機不支援 steer，草稿已保留'
      : r?.status === 'rejected' ? 'Steer 被拒絕，草稿與圖片已保留'
        : `Steer 未送達，草稿與圖片已保留${r?.reason ? '：' + r.reason : ''}`)
    return r || { status: 'rejected' }
  }
  function onKey(ev) {
    const s = settings()
    if (!s.steerKey || !matchesChord(ev, s.steerKey)) return false
    const el = ev.target?.closest?.(EDITOR_SELECTOR)
    const sid = host.state.focusedSessionId.get()
    if (!el || !sid || !(host.state.busyBySession.get() || {})[sid]) return false
    ev.preventDefault(); ev.stopPropagation()
    void steer(sid)
    return true
  }
  return { steer, onKey }
}

export async function ensureQueueMode(host, sessionId, done) {
  if (!sessionId || done.has(sessionId)) return false
  done.add(sessionId)
  try { await host.request('config.set', { session_id: sessionId, key: 'busy', value: 'queue' }); return true } catch { return false }
}

// ------------------------------------------------------------------ UI

function useCtrl(ctrl) {
  const [s, setS] = useState(ctrl.get())
  useEffect(() => ctrl.subscribe(setS), [ctrl])
  return s
}

function Pill({ ctrl, accept, copy }) {
  const s = useCtrl(ctrl)
  if (!s.suggestion || s.filled) return null
  const btn = 'rounded px-1.5 py-0.5 text-[0.6875rem] text-(--ui-text-tertiary) hover:bg-(--ui-bg-hover)'
  return jsxs('div', {
    className: 'flex max-w-full items-center gap-1 px-2 py-1 text-xs',
    children: [
      jsx('button', {
        type: 'button', title: '點一下填入輸入框（Tab 亦可）', onClick: () => void accept(),
        className: 'min-w-0 truncate rounded-full border border-(--ui-border) px-2.5 py-0.5 text-left text-(--ui-text-secondary) opacity-80 hover:opacity-100',
        children: `↳ ${s.suggestion}`
      }),
      jsx('button', {
        type: 'button', title: '複製', className: btn,
        onClick: () => void copy(s.suggestion)
      , children: '⧉' }),
      jsx('button', { type: 'button', title: '關閉', className: btn, onClick: () => ctrl.clear(), children: '✕' })
    ]
  })
}

export function createHostAdapterClient({ fetchImpl, settings, files }) {
  return {
    async run(action) {
      if (!['check', 'status', 'install', 'rollback'].includes(action)) throw new Error('unknown host-adapter action')
      const s = settings()
      let base
      try { base = new URL(s.url) } catch { throw new Error('主機安裝僅支援 loopback 本機服務 URL') }
      if (base.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(base.hostname)
          || base.username || base.password || base.pathname !== '/' || base.search || base.hash) {
        throw new Error('主機安裝僅支援 loopback 本機服務 URL（不可含帳密或路徑）')
      }
      let token = s.controlToken || s.token
      if (!token && files?.readText) {
        const credential = await files.readText('data', 'control.json')
        if (credential.ok) token = JSON.parse(credential.text).token
      }
      if (!token) throw new Error('請先設定主機控制 Token 或服務 Token；主機安裝必須驗證')
      const mutation = action === 'install' || action === 'rollback'
      const response = await fetchImpl(`${base.origin}/v1/host-adapter/${action}`, {
        method: mutation ? 'POST' : 'GET',
        headers: { Authorization: `Bearer ${token}`, ...(mutation ? { 'Content-Type': 'application/json' } : {}) },
        ...(mutation ? { body: JSON.stringify({ confirm: true }) } : {}),
        signal: AbortSignal.timeout(mutation ? 3700000 : 15000)
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`)
      return body
    }
  }
}

export async function probeHostAdapter(runtime) {
  const sdk = typeof runtime.composer?.steerStrict === 'function'
  const sessionId = runtime.state?.focusedSessionId?.get()
  if (!sdk || !sessionId) return { sdk, backend: false, reason: sdk ? '請先選擇工作階段' : '目前 Renderer 沒有 steerStrict；請重建並重新啟動 Desktop' }
  try {
    const caps = await runtime.request('neo.composer.capabilities', { session_id: sessionId, protocol: 1 })
    const backend = caps?.protocol === 1 && caps.image_mode === 'vision_analyze_reference'
    return { sdk, backend, reason: backend ? '目前工作階段 Gateway protocol 1 已確認（送達仍須每次回執）' : 'Gateway 尚未確認相容能力' }
  } catch (err) { return { sdk, backend: false, reason: `Gateway 能力未確認：${String(err?.message || err)}` } }
}

export function describeHostAdapter(state) {
  if (state.desktop?.state === 'waiting_for_exit') return 'Windows 桌面版已建置並驗證。請結束 Hermes（含系統匣）；服務會自動套用並重新開啟。'
  if (state.desktop?.state === 'installed') return 'Windows 桌面版已套用；執行中能力仍以 Renderer SDK 與 Gateway 檢查為準。'
  if (['failed', 'promotion_failed'].includes(state.desktop?.state)) return `安裝未完成：${state.desktop.error}；建置記錄：${state.desktop.log || ''}`
  const backend = state.backend?.source_applied ? '後端原始碼已套用；Gateway 仍須重新啟動' : '後端原始碼尚未套用'
  const frontend = state.frontend?.state === 'source_missing' ? '此安裝缺少 Desktop 原始碼，無法在此重建 Renderer'
    : state.frontend?.state === 'rollback_rebuild_required' ? '已回復原始碼；已部署的 Renderer 仍須回復／重建'
      : state.frontend?.source_applied || state.frontend?.rebuild_required ? '前端原始碼已套用；仍須重建並部署 Renderer'
        : '前端原始碼尚未套用'
  return `${backend}。${frontend}。`
}

export function HostAdapterSettings({ settings, files }) {
  const [status, setStatus] = useState('尚未檢查主機 Adapter')
  const [runtime, setRuntime] = useState('執行中能力尚未確認')
  const [working, setWorking] = useState(false)
  const [canRollback, setCanRollback] = useState(false)
  const action = async name => {
    setWorking(true)
    setStatus(name === 'install' ? '正在備份、安裝與建置 Windows 桌面版，請保持 Hermes 開啟…' : name === 'rollback' ? '正在回復上次安裝…' : '正在檢查…')
    try {
      const client = createHostAdapterClient({ fetchImpl: (...args) => fetch(...args), settings: () => settings, files })
      const result = await client.run(name)
      setStatus(`${result.root ? result.root + ' · ' : ''}${describeHostAdapter(result)}`)
      setCanRollback(!!result.rollback_available)
      const caps = await probeHostAdapter(host)
      setRuntime(`Renderer SDK：${caps.sdk ? '已提供' : '缺少'} · ${caps.reason}`)
    } catch (err) { setStatus(`主機操作未完成：${String(err?.message || err)}`) }
    finally { setWorking(false) }
  }
  const button = (label, name, disabled = false) => jsx('button', {
    type: 'button', disabled: working || disabled, onClick: () => action(name),
    className: 'rounded border border-(--ui-border) px-2 py-1 disabled:opacity-50', children: label
  })
  return jsxs('div', { className: 'flex flex-col gap-2 border-t border-(--ui-border) pt-3', children: [
    jsx('div', { className: 'font-medium', children: '選用：嚴格 Steer 主機 Adapter' }),
    jsx('p', { className: 'text-(--ui-text-tertiary)', children: '點擊安裝會備份並修改本機已安裝的 Hermes 原始碼。相容性依結構與能力檢查，不依 Hermes 版本號。' }),
    jsxs('div', { className: 'flex flex-wrap gap-2', children: [button('檢查主機介面', 'check'), button('安裝主機 Adapter', 'install'), button('回復上次安裝', 'rollback', !canRollback)] }),
    jsx('p', { role: 'status', className: 'break-all text-(--ui-text-secondary)', children: status }),
    jsx('p', { className: 'text-(--ui-text-tertiary)', children: runtime }),
    jsx('p', { className: 'text-(--ui-text-tertiary)', children: 'Windows 安裝會自動備份、套用 Adapter 並在本機建置桌面版，不需要 WSL。顯示建置完成後，請結束 Hermes（含系統匣）；服務會套用並自動重新開啟。Token 自動設定，框內建議不需要此 Adapter。' })
  ] })
}

function Settings({ ctrl, storage, files }) {
  const [v, setV] = useState(ctrl.settings())
  const [health, setHealth] = useState('')
  const save = next => {
    setV(next); storage.set('settings', next); ctrl.clear()
  }
  const field = (label, key, type = 'text') => jsxs('label', {
    className: 'flex flex-col gap-1',
    children: [jsx('span', { className: 'text-(--ui-text-tertiary)', children: label }),
      jsx('input', { type, value: v[key], className: 'rounded border border-(--ui-border) bg-transparent px-2 py-1',
        onChange: e => save({ ...v, [key]: e.target.value }) })]
  })
  const check = (label, key) => jsxs('label', {
    className: 'flex items-center gap-2',
    children: [jsx('input', { type: 'checkbox', checked: !!v[key], onChange: e => save({ ...v, [key]: e.target.checked }) }),
      jsx('span', { children: label })]
  })
  const test = async () => {
    try {
      if (v.backend === 'hermes') {
        const runtime = await host.request('runtime.describe')
        if (!runtime.capabilities?.includes('plugin-rpc-v1')) throw new Error('Gateway 不支援 plugin RPC')
        const sid = host.state.focusedSessionId.get()
        if (!sid) throw new Error('請先選擇工作階段')
        if (host.state.focusedSessionProfile.get() !== host.state.profile.get()) throw new Error('請先啟用此工作階段的 profile')
        const result = await host.request('plugin.neo-composer.predict', { session_id: sid, messages: [
          { role: 'user', content: '請說明 Hermes 模型設定在哪裡。' },
          { role: 'assistant', content: '可以在 Settings 的 Models 頁面設定。' }
        ] })
        setHealth(`Hermes 模型呼叫完成 · ${result.status}${result.suggestion ? ' · ' + result.suggestion : ''}`)
        return
      }
      const r = await fetch(`${v.url.replace(/\/$/, '')}/healthz`)
      const b = await r.json()
      setHealth(`OK ${b.version} · ${b.live_model || b.models?.join(',')}${b.last_error ? ' · ' + b.last_error : ''}`)
    } catch (e) { setHealth(`連不上：${e?.message || e}`) }
  }
  return jsxs('div', {
    className: 'flex max-w-md flex-col gap-3 p-4 text-sm',
    children: [
      jsx('div', { className: 'font-medium', children: `Neo Composer ${VERSION}` }),
      check('啟用灰字建議', 'enabled'),
      check('框內灰字（Tab 填入）', 'inline'),
      check('忙碌時 Enter 排隊（Shift+Enter 換行）', 'enterQueues'),
      field('忙碌時 Steer 快捷鍵（例：ctrl+enter）', 'steerKey'),
      jsxs('label', { className: 'flex flex-col gap-1', children: [
        jsx('span', { children: '建議模型來源' }),
        jsxs('select', { value: v.backend, onChange: e => save({ ...v, backend: e.target.value }), children: [
          jsx('option', { value: 'hermes', children: 'Hermes 已設定的模型' }),
          jsx('option', { value: 'service', children: '獨立 Neo Suggest service' })
        ] })
      ] }),
      jsx('button', { type: 'button', onClick: () => host.navigate('/settings?tab=config:model&aux=neo_composer'), children: '選擇 Hermes 模型' }),
      jsx('p', { children: 'Hermes 模式使用 Auxiliary → Neo Composer，最多傳送 8 則對話並使用該模型額度；憑證由 Hermes 管理。模型變更後請重新產生建議。service 仍提供主機 Adapter 控制。' }),
      jsx('button', { type: 'button', onClick: () => {
        const sid = host.state.focusedSessionId.get()
        if (!(host.state.busyBySession.get() || {})[sid]) void ctrl.refresh(sid)
      }, children: '重新產生建議' }),
      field('Suggest service URL', 'url'),
      field('Token（建議服務；主機控制未另設時共用）', 'token', 'password'),
      field('主機控制 Token（選填；NEO_CONTROL_TOKEN）', 'controlToken', 'password'),
      jsxs('div', { className: 'flex items-center gap-2', children: [
        jsx('button', { type: 'button', className: 'rounded border border-(--ui-border) px-2 py-1', onClick: test, children: '測試連線' }),
        jsx('span', { className: 'text-(--ui-text-tertiary)', children: health })] }),
      jsx(HostAdapterSettings, { settings: v, files })
    ]
  })
}

// ------------------------------------------------------------------ plugin

export default {
  id: 'neo-composer',
  name: 'Neo Composer',
  register(ctx) {
    const context = () => ({
      session: host.state.focusedSessionId.get(),
      profile: host.state.focusedSessionProfile?.get(),
      gatewayProfile: host.state.profile?.get(),
      gateway: host.state.gateway?.get()
    })
    const ctrl = createController({ fetchImpl: (...a) => fetch(...a), request: host.request, storage: ctx.storage, context })
    const accept = async () => {
      const { suggestion: text, sessionId } = ctrl.get()
      if (!text || sessionId !== host.state.focusedSessionId.get()) return false
      const draft = await host.composer.getDraft(sessionId)
      if (draft === null || draft.trim() || sessionId !== host.state.focusedSessionId.get()) return false
      const ok = await host.composer.setDraft(sessionId, text)
      if (ok) { ctrl.setFilled(true); host.composer.focus(sessionId) }
      return ok
    }

    const copy = async text => {
      const ok = await ctx.os?.writeClipboard(text)
      host.notify?.({ kind: ok ? 'info' : 'error', message: ok ? '已複製建議' : '無法存取剪貼簿，可點擊建議填入輸入框' })
      return !!ok
    }

    // Trigger: focused session finished a turn, or focus moved to an idle session.
    let lastSid = null
    let lastBusy = false
    const evaluate = () => {
      const sid = host.state.focusedSessionId.get()
      const busy = !!(host.state.busyBySession.get() || {})[sid]
      if (busy) { if (ctrl.get().suggestion || ctrl.get().status === 'loading') ctrl.clear() }
      else if (sid !== lastSid || lastBusy) void ctrl.refresh(sid)
      lastSid = sid
      lastBusy = busy
    }
    const steerKey = createSteerKey({ host, settings: () => ctrl.settings() })
    const queued = new Set()
    const keyListener = ev => { steerKey.onKey(ev) }
    if (typeof document !== 'undefined') document.addEventListener('keydown', keyListener, true)
    const applyQueue = () => {
      const sid = host.state.focusedSessionId.get()
      if (ctrl.settings().enterQueues && (host.state.busyBySession.get() || {})[sid]) void ensureQueueMode(host, sid, queued)
    }
    const unsubs = [
      () => { if (typeof document !== 'undefined') document.removeEventListener('keydown', keyListener, true) },
      host.state.busyBySession.listen(applyQueue),
      host.state.focusedSessionId.listen(evaluate),
      host.state.busyBySession.listen(evaluate),
      ...[host.state.focusedSessionProfile, host.state.profile, host.state.gateway].filter(Boolean).map(store => store.listen(() => {
        ctrl.clear(); lastSid = null; evaluate()
      })),
      installInline(ctrl, accept)
    ]
    evaluate()

    ctx.registerMany([
      { id: 'pill', area: COMPOSER_AREAS.underside, order: 40, render: () => jsx(Pill, { ctrl, accept, copy }) },
      { id: 'accept', area: KEYBINDS_AREA, data: {
        id: 'neo-composer.accept', label: '填入灰字建議', category: 'Neo Composer',
        defaults: ['mod+shift+enter'], run: () => accept() } },
      { id: 'refresh', area: PALETTE_AREA, data: {
        id: 'neo-composer.refresh', label: 'Neo Composer: 重新產生建議', keywords: ['neo', 'suggest', '灰字'],
        run: () => void ctrl.refresh(host.state.focusedSessionId.get()) } }
    ])
    ctx.registerSettingsPage?.({ id: 'neo-composer', title: 'Neo Composer', render: () => jsx(Settings, { ctrl, storage: ctx.storage, files: ctx.files }) })

    ctx.onDispose?.(() => { ctrl.clear(); for (const u of unsubs) u?.() })
  }
}
