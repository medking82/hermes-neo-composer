import { atom, useValue, host, Button, COMPOSER_AREAS, KEYBINDS_AREA, PALETTE_AREA } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'

// Exported for deterministic SDK-contract tests; no app internals or DOM access.
export function createController(ctx, api = host) {
  const view = atom({ text: '', status: '', loading: false, enabled: true })
  let epoch = 0
  let disposed = false
  let candidate = null
  let accepting = false
  let invalidation = Promise.resolve()
  let previous = ''
  let previousBusy = false
  const address = () => ({
    id: api.state.focusedSessionId.get(),
    key: api.state.focusedStoredSessionId.get() || api.state.focusedSessionId.get(),
    profile: api.state.focusedSessionProfile.get() || api.state.profile.get(),
    gatewayProfile: api.state.profile.get(),
    gateway: api.state.gateway.get()
  })
  const busy = s => !!api.state.busyBySession.get()[s.id]
  const current = (s, n) => !disposed && epoch === n && JSON.stringify(address()) === JSON.stringify(s)
  const same = (s, n) => current(s, n) && !busy(s)
  const post = (path, body) => ctx.rest(path, { method: 'POST', body })
  const clear = (status = '') => { candidate = null; view.set({ ...view.get(), text: '', loading: false, status }) }
  const fail = error => error instanceof Error ? error.message : String(error)

  async function refresh(force = false) {
    const n = ++epoch
    const s = address()
    clear()
    if (!s.id || busy(s)) return
    // RPC uses the active gateway; REST uses its active profile. Never mix a
    // focused bot from another profile with the gateway's context or storage.
    if (s.profile !== s.gatewayProfile) {
      clear('Activate this session’s profile to generate a candidate.')
      return
    }
    view.set({ ...view.get(), loading: true })
    try {
      await invalidation
      if (!same(s, n)) return
      const settings = await ctx.rest('/settings')
      if (!same(s, n)) return
      view.set({ ...view.get(), enabled: settings.enabled })
      if (!settings.enabled) { clear('Suggestions disabled'); return }
      const runtime = await api.request('runtime.describe')
      if (!same(s, n)) return
      if (!runtime.capabilities?.includes('plugin-rpc-v1')) {
        clear('This gateway does not expose plugin RPC generation.')
        return
      }
      const history = await api.request('session.history', { session_id: s.id })
      if (!same(s, n)) return
      const rows = Array.isArray(history) ? history : history.messages
      // Filter tools; take a bounded excerpt without changing the host transcript.
      const messages = (rows || []).filter(r => ['user', 'assistant'].includes(r.role) && typeof r.text === 'string')
        .slice(-8).map(r => ({ role: r.role, content: r.text.slice(-2800) }))
      if (!messages.length) { clear('No conversation to predict from'); return }
      const prepared = await post('/prepare', { session_id: s.key, messages, refresh: force })
      if (!same(s, n)) return
      const result = prepared.status === 'pending'
        ? await api.request('plugin.neo-composer.suggest', {
          session_id: s.id, stored_session_id: s.key, messages, token: prepared.token
        }) : prepared
      if (!same(s, n)) return
      // A disable/re-enable in another window changes revision. Re-read settings
      // after async generation, even when the result came from durable storage.
      const liveSettings = await ctx.rest('/settings')
      if (!same(s, n)) return
      if (!liveSettings.enabled || liveSettings.revision !== settings.revision) {
        clear('Settings changed; refresh to generate again')
        return
      }
      candidate = result.text ? { ...s, text: result.text, token: result.token, settingsRevision: liveSettings.revision, epoch: n } : null
      view.set({ ...view.get(), text: result.text || '', loading: false,
        status: result.text ? '' : 'No grounded candidate; refresh when useful' })
    } catch (error) {
      if (same(s, n)) clear(fail(error))
    }
  }

  async function accept() {
    const c = candidate
    if (!c || accepting || !same(capture(c), c.epoch)) return
    accepting = true
    try {
      const settings = await ctx.rest('/settings')
      if (!same(capture(c), c.epoch)) return
      if (!settings.enabled || settings.revision !== c.settingsRevision) {
        clear('Settings changed; refresh to generate again')
        return
      }
      const draft = await api.composer.getDraft(c.id)
      if (!same(capture(c), c.epoch) || draft !== '') return
      // Insert instead of replacing: typing between the separate SDK read and
      // write calls must remain in the draft, even if acceptance races a key.
      if (await api.composer.insertText(c.id, c.text, { mode: 'inline' })) {
        if (same(capture(c), c.epoch)) clear()
        api.composer.focus(c.id)
        await post('/dismiss', { session_id: c.key, token: c.token })
      }
    } catch (error) {
      if (same(capture(c), c.epoch)) view.set({ ...view.get(), status: fail(error) })
    } finally { accepting = false }
  }
  function capture(c) {
    const { id, key, profile, gatewayProfile, gateway } = c
    return { id, key, profile, gatewayProfile, gateway }
  }
  async function copy() {
    const c = candidate
    if (!c || !same(capture(c), c.epoch)) return
    const ok = await ctx.os.writeClipboard(c.text)
    if (!disposed) api.notify({ kind: ok ? 'success' : 'error', message: ok ? 'Candidate copied' : 'Clipboard unavailable' })
  }
  async function dismiss() {
    const c = candidate
    ++epoch
    clear()
    if (c) {
      try { await post('/dismiss', { session_id: c.key, token: c.token }) }
      catch (error) { if (!disposed) view.set({ ...view.get(), status: fail(error) }) }
    }
  }
  async function toggle() {
    const s = address()
    const n = ++epoch
    clear()
    try {
      const settings = await ctx.rest('/settings')
      if (!current(s, n)) return
      const changed = await post('/settings', { enabled: !settings.enabled })
      if (!current(s, n)) return
      view.set({ ...view.get(), enabled: changed.enabled })
      if (changed.enabled) await refresh()
    } catch (error) { if (current(s, n)) clear(fail(error)) }
  }
  function changed() {
    if (disposed) return
    const s = address()
    const identity = JSON.stringify(s)
    const working = busy(s)
    if (identity === previous && working === previousBusy) return
    previous = identity
    previousBusy = working
    ++epoch
    clear()
    // Invalidate requests in flight on a new turn; focus/profile changes already
    // invalidate renderer results and never send a write to the previous profile.
    if (working && s.id && s.profile === s.gatewayProfile) {
      invalidation = post('/invalidate', { session_id: s.key }).catch(() => {})
    }
    if (!working) void refresh()
  }
  const disposers = [api.state.focusedSessionId, api.state.focusedStoredSessionId,
    api.state.focusedSessionProfile, api.state.profile, api.state.gateway, api.state.busyBySession]
    .map(store => store.listen(changed))
  ctx.onDispose(() => { disposed = true; ++epoch; clear(); disposers.forEach(dispose => dispose()) })
  changed()
  return { view, refresh, accept, copy, dismiss, toggle }
}

export default {
  id: 'neo-composer', name: 'Neo Composer', defaultEnabled: false,
  register(ctx) {
    const controller = createController(ctx)
    function Candidate() {
      const state = useValue(controller.view)
      return jsx('div', { style: { display: 'flex', gap: 6, alignItems: 'center', color: 'var(--ui-text-secondary)', fontSize: 12 }, children: [
        state.text ? jsx(Button, { size: 'sm', variant: 'ghost', title: state.text, onClick: controller.accept, children: state.text }, 'accept')
          : jsx('span', { role: 'status', children: state.loading ? 'Predicting…' : state.status }, 'status'),
        state.text && jsx(Button, { size: 'sm', variant: 'ghost', onClick: controller.copy, children: 'Copy' }, 'copy'),
        state.text && jsx(Button, { size: 'sm', variant: 'ghost', onClick: controller.dismiss, children: 'Dismiss' }, 'dismiss'),
        jsx(Button, { size: 'sm', variant: 'ghost', disabled: state.loading, onClick: () => void controller.refresh(true), children: 'Refresh' }, 'refresh')
      ] })
    }
    function Settings() {
      const state = useValue(controller.view)
      return jsx('div', { children: [
        jsx('p', { children: 'Candidates use your active Hermes model and quota. Up to eight recent user/assistant messages are sent to that provider. Candidate text is cached in this profile’s plugin data for one day; expired rows are pruned on database access.' }, 'disclosure'),
        jsx(Button, { onClick: controller.toggle, children: state.enabled ? 'Disable suggestions' : 'Enable suggestions' }, 'toggle')
      ] })
    }
    ctx.register({ id: 'candidate', area: COMPOSER_AREAS.underside, render: () => jsx(Candidate, {}) })
    ctx.registerSettingsPage({ id: 'settings', title: 'Neo Composer', render: () => jsx(Settings, {}) })
    ctx.register({ id: 'accept', area: KEYBINDS_AREA, data: {
      id: 'neo-composer.accept', label: 'Neo Composer: fill empty draft', defaults: [], run: () => void controller.accept()
    } })
    ctx.register({ id: 'refresh', area: PALETTE_AREA, data: {
      id: 'neo-composer.refresh', label: 'Neo Composer: refresh candidate', run: () => void controller.refresh(true)
    } })
  }
}
