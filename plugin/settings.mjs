// Inject only the documented SDK/React surface; shared with browser acceptance.
export function createSettingsView({ jsx, useEffect, useRef, useState, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue }) {
  return function PredictionSettings({ ctx }) {
    const [view, setView] = useState(null)
    const [draft, setDraft] = useState(null)
    const [busy, setBusy] = useState(false)
    const [notice, setNotice] = useState('')
    const epoch = useRef(0)
    const load = async () => {
      const id = ++epoch.current
      setBusy(true); setNotice(''); setView(null); setDraft(null)
      try {
        const next = await ctx.rest('/settings')
        if (id !== epoch.current) return
        setView(next); setDraft(next.settings)
      } catch { if (id === epoch.current) setNotice('Settings unavailable. Check the active profile and backend compatibility.') }
      finally { if (id === epoch.current) setBusy(false) }
    }
    useEffect(() => { void load(); return () => { epoch.current++ } }, [ctx])
    const save = async () => {
      const id = ++epoch.current
      setBusy(true); setNotice('')
      try {
        const next = await ctx.rest('/settings', { method: 'POST', body: { scope: view.scope, settings: draft } })
        if (id !== epoch.current) return
        setView(next); setDraft(next.settings); setNotice('Saved. Changes apply to the next prediction context.')
      } catch { if (id === epoch.current) setNotice('Not saved. The profile or connection may have changed. Reload settings and try again.') }
      finally { if (id === epoch.current) setBusy(false) }
    }
    const field = (name, label, empty) => jsx('label', { style: { display: 'grid', gap: 8 }, children: [
      jsx('span', { children: label }),
      jsx(Select, { value: draft[name] || '__auto', disabled: busy, onValueChange: value => setDraft({ ...draft, [name]: value === '__auto' ? '' : value }), children: [
        jsx(SelectTrigger, { 'aria-label': label, children: jsx(SelectValue, {}) }),
        jsx(SelectContent, { children: [jsx(SelectItem, { value: '__auto', children: empty }, '__auto'),
          ...view.catalog.filter(row => draft.providers.includes(row.provider)).map(row => jsx(SelectItem, { value: `${row.provider}/${row.model}`, children: `${row.provider} / ${row.model}` }, `${row.provider}/${row.model}`))] })
      ] })
    ] }, name)
    return jsx('section', { 'aria-label': 'Neo Composer settings', style: { padding: 24, maxWidth: 720, color: 'var(--ui-text-primary)', display: 'grid', gap: 20 }, children: [
      jsx('header', { children: [jsx('h2', { style: { fontSize: 20, fontWeight: 600 }, children: 'Neo Composer' }), jsx('p', { style: { color: 'var(--ui-text-secondary)' }, children: 'Prediction settings · suggestions stay drafts until you send them.' })] }),
      !draft ? jsx('p', { role: 'status', children: busy ? 'Loading settings…' : 'No settings loaded.' }) : jsx('div', { style: { display: 'grid', gap: 20 }, children: [
        jsx('label', { style: { display: 'flex', alignItems: 'center', gap: 12 }, children: [jsx(Switch, { checked: draft.enabled, disabled: busy, 'aria-label': 'Ghost-text predictions', onCheckedChange: enabled => setDraft({ ...draft, enabled }) }), 'Ghost-text predictions'] }),
        jsx('fieldset', { children: [jsx('legend', { children: 'Approved providers' }), jsx('p', { style: { color: 'var(--ui-text-secondary)' }, children: 'Only these already-connected providers may receive a short conversation excerpt. No credentials or endpoints are added.' }),
          ...[...new Set([...draft.providers, ...view.catalog.map(row => row.provider)])].map(provider => jsx('label', { style: { display: 'flex', gap: 8, alignItems: 'center', paddingTop: 8 }, children: [jsx(Checkbox, { checked: draft.providers.includes(provider), disabled: busy, 'aria-label': provider, onCheckedChange: checked => {
            const providers = checked ? [...draft.providers, provider] : draft.providers.filter(p => p !== provider)
            const keep = value => !value || providers.includes(value.split('/')[0]) ? value : ''
            setDraft({ ...draft, providers, model: keep(draft.model), fallback: keep(draft.fallback) })
          } }), provider] }, provider))] }),
        field('model', 'Prediction model', 'Automatic — lowest verified cost'),
        field('fallback', 'Low-cost fallback', 'None — disable if cost is unknown'),
        jsx('p', { style: { color: 'var(--ui-text-secondary)' }, children: 'Unknown costs are never guessed. Subscription quotas and API prices are not compared. Automatic ranking uses verified text capability and a fixed short-text budget; it is not a guarantee of the final bill.' }),
        jsx('div', { role: 'status', children: [jsx('strong', { children: view.selection.route ? `${view.selection.route.provider} / ${view.selection.route.model}` : 'Prediction paused' }), jsx('p', { children: view.selection.reason })] }),
        jsx('p', { style: { color: 'var(--ui-text-secondary)' }, children: 'Main chat model, Fast mode and reasoning effort stay unchanged. Prediction effort: Low. No automatic retry or fallback after a failed request.' }),
        jsx(Button, { onClick: save, disabled: busy, children: busy ? 'Saving…' : 'Save prediction settings' })
      ] }),
      jsx('p', { role: 'status', children: notice }),
      jsx(Button, { variant: 'outline', onClick: load, disabled: busy, children: 'Reload settings' }),
      jsx('p', { style: { color: 'var(--ui-text-secondary)', fontSize: 12 }, children: 'Tab accepts editable text · Esc dismisses · Enter while busy queues · Ctrl+Enter steers · Shift+Enter adds a line' })
    ] })
  }
}
