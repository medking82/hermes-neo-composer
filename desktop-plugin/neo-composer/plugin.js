// Neo Composer v0.5 — ghost-text next-prompt suggestions for Hermes Desktop.
//
// Durability contract: only `@hermes/plugin-sdk` public surface + the standalone
// neo-suggest HTTP service. No Hermes core patch.
//   * stable path  : COMPOSER_AREAS.underside pill (click = fill composer, copy button)
//   * enhancer     : in-box ghost text via the composer's placeholder attribute and
//                    Tab-to-accept. It is feature-detected; if a Hermes update
//                    renames the editor slot, the enhancer silently turns off and
//                    the pill keeps working.
import { COMPOSER_AREAS, KEYBINDS_AREA, PALETTE_AREA, host, writeClipboardText } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

export const VERSION = '0.5.0'
export const EDITOR_SELECTOR = "[data-slot='composer-rich-input']"
export const DEFAULTS = { url: 'http://127.0.0.1:3460', token: '', enabled: true, inline: true }
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

export function createController({ fetchImpl, request, storage, now = () => Date.now() }) {
  const listeners = new Set()
  let state = { sessionId: null, suggestion: null, status: 'idle', error: null }
  let seq = 0
  const settings = () => ({ ...DEFAULTS, ...(storage?.get('settings', {}) || {}) })
  const set = patch => {
    state = { ...state, ...patch }
    for (const fn of listeners) fn(state)
  }

  async function refresh(sessionId) {
    const s = settings()
    const my = ++seq
    if (!s.enabled || !sessionId) return set({ sessionId, suggestion: null, status: 'idle' })
    set({ sessionId, suggestion: null, status: 'loading', error: null })
    try {
      const history = await request('session.history', { session_id: sessionId })
      const messages = toServiceMessages(history)
      if (my !== seq) return
      if (!messages.length || messages[messages.length - 1].role !== 'assistant') {
        return set({ status: 'idle' })
      }
      const headers = { 'Content-Type': 'application/json' }
      if (s.token) headers.Authorization = `Bearer ${s.token}`
      const resp = await fetchImpl(`${s.url.replace(/\/$/, '')}/v1/suggest`, {
        method: 'POST', headers, body: JSON.stringify({ messages, client: `hermes-desktop/${VERSION}` })
      })
      const body = await resp.json().catch(() => ({}))
      if (my !== seq) return
      if (!resp.ok) return set({ status: 'error', error: body.error || `HTTP ${resp.status}` })
      set({ suggestion: body.suggestion || null, status: body.suggestion ? 'ready' : body.status || 'empty', at: now() })
    } catch (err) {
      if (my === seq) set({ status: 'error', error: String(err?.message || err) })
    }
  }

  return {
    get: () => state,
    settings,
    subscribe(fn) { listeners.add(fn); fn(state); return () => listeners.delete(fn) },
    refresh,
    clear() { seq++; set({ suggestion: null, status: 'idle' }) }
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
  const mo = new MutationObserver(() => { if (!applying) paint() })
  mo.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-placeholder'] })
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

// ------------------------------------------------------------------ UI

function useCtrl(ctrl) {
  const [s, setS] = useState(ctrl.get())
  useEffect(() => ctrl.subscribe(setS), [ctrl])
  return s
}

function Pill({ ctrl, accept }) {
  const s = useCtrl(ctrl)
  if (!s.suggestion) return null
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
        onClick: () => void writeClipboardText(s.suggestion).then(() => host.notify?.({ kind: 'info', message: '已複製建議' }))
      , children: '⧉' }),
      jsx('button', { type: 'button', title: '關閉', className: btn, onClick: () => ctrl.clear(), children: '✕' })
    ]
  })
}

function Settings({ ctrl, storage }) {
  const [v, setV] = useState(ctrl.settings())
  const [health, setHealth] = useState('')
  const save = next => { setV(next); storage.set('settings', next) }
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
      field('Suggest service URL', 'url'),
      field('Token（選填）', 'token', 'password'),
      jsxs('div', { className: 'flex items-center gap-2', children: [
        jsx('button', { type: 'button', className: 'rounded border border-(--ui-border) px-2 py-1', onClick: test, children: '測試連線' }),
        jsx('span', { className: 'text-(--ui-text-tertiary)', children: health })] })
    ]
  })
}

// ------------------------------------------------------------------ plugin

export default {
  id: 'neo-composer',
  name: 'Neo Composer',
  register(ctx) {
    const ctrl = createController({ fetchImpl: (...a) => fetch(...a), request: host.request, storage: ctx.storage })
    const accept = async () => {
      const { suggestion: text, sessionId } = ctrl.get()
      if (!text || sessionId !== host.state.focusedSessionId.get()) return false
      const draft = await host.composer.getDraft(sessionId)
      if (draft === null || draft.trim() || sessionId !== host.state.focusedSessionId.get()) return false
      const ok = await host.composer.setDraft(sessionId, text)
      if (ok) { ctrl.clear(); host.composer.focus(sessionId) }
      return ok
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
    const unsubs = [
      host.state.focusedSessionId.listen(evaluate),
      host.state.busyBySession.listen(evaluate),
      installInline(ctrl, accept)
    ]
    evaluate()

    ctx.registerMany([
      { id: 'pill', area: COMPOSER_AREAS.underside, order: 40, render: () => jsx(Pill, { ctrl, accept }) },
      { id: 'accept', area: KEYBINDS_AREA, data: {
        id: 'neo-composer.accept', label: '填入灰字建議', category: 'Neo Composer',
        defaults: ['mod+shift+enter'], run: () => accept() } },
      { id: 'refresh', area: PALETTE_AREA, data: {
        id: 'neo-composer.refresh', label: 'Neo Composer: 重新產生建議', keywords: ['neo', 'suggest', '灰字'],
        run: () => void ctrl.refresh(host.state.focusedSessionId.get()) } }
    ])
    ctx.registerSettingsPage?.({ id: 'neo-composer', title: 'Neo Composer', render: () => jsx(Settings, { ctrl, storage: ctx.storage }) })

    ctx.onDispose?.(() => { for (const u of unsubs) u?.() })
  }
}
