import { host, ROUTES_AREA, SIDEBAR_NAV_AREA, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx } from 'react/jsx-runtime'
// Portable plugin policy: no app-private imports, DOM handlers, tools or auto-send.
const readOnlyKeys = {'composer.queue':['enter'],'composer.steer':['mod+enter']}
function keyAction(e) {
  if(e.key!=='Enter'||e.shiftKey||e.altKey||!e.busy) return undefined
  return e.ctrlKey||e.metaKey ? 'steer' : 'queue'
}
const validRow = row => row && row.status==='ready' && typeof row.text==='string' && row.text.trim() &&
  Array.from(row.text).length<=240 && !/[\p{Cc}\p{Cf}\u2028\u2029]/u.test(row.text) &&
  /^[a-f0-9]{64}$/.test(row.version) && /^[a-f0-9]{32}$/.test(row.request_id)

function ledger(storage) {
  const saved=storage.get('decisions',null)
  if(saved && typeof saved==='object' && !Array.isArray(saved)) return saved
  let legacy={}
  try { legacy=JSON.parse(globalThis.localStorage?.getItem('hermes.nextPrompt.decisions.v1')||'{}') } catch {}
  if(!legacy||typeof legacy!=='object'||Array.isArray(legacy)) legacy={}
  storage.set('decisions',legacy)
  return legacy
}
const keyFor=c=>JSON.stringify([c.connectionId||'local',c.profile||'default',c.storedId])
function remember(storage,key,decision) {
  const all={...ledger(storage),[key]:decision}
  storage.set('decisions',all)
  if(JSON.stringify(storage.get('decisions',{})[key])!==JSON.stringify(decision)) throw Error('Decision persistence unavailable')
}
function profileLifecycle(storage,event) {
  const all={...ledger(storage)}
  for(const key of Object.keys(all)) {
    let parts;try {parts=JSON.parse(key)} catch {continue}
    if(!Array.isArray(parts)||parts.length!==3) continue
    const [connection,profile,session]=parts
    if(event.kind==='drop' && connection===(event.connectionId||'local') && profile===event.profile) delete all[key]
    if(event.kind==='rename' && connection==='local' && profile===event.from) {
      const moved=JSON.stringify([connection,event.to,session]);all[moved]??=all[key];delete all[key]
    }
  }
  storage.set('decisions',all)
}
function createController(env,storage) {
  const c=env.context,key=keyFor(c),timers=new Set()
  let disposed=false,expired=false,started=false,settledSeen=false,inFlight=false,catchUpPending=false,row=null,state={enabled:false,empty:false}
  const visible=()=>!disposed&&!expired&&!c.busy&&state.enabled&&state.empty&&validRow(row) ? row.text : null
  const publish=()=>env.publish(visible())
  const decision=(candidate,status)=>({root:candidate.root,version:candidate.version,request_id:candidate.request_id,status})
  const acknowledge=d=>{void env.request('/decision',d).catch(()=>{})}
  const consumeLate=candidate=>{
    if(!validRow(candidate)||candidate.root!==c.storedId) return
    // A transport timeout is not an Esc gesture. Persist the terminal local
    // outcome, without fabricating a user decision on the backend.
    try {remember(storage,key,decision(candidate,'timeout'))} catch {}
  }
  const start=()=>{
    if(disposed||expired||started||inFlight||c.busy||!state.enabled||!state.empty||!c.sessionId||!c.storedId) return
    started=true;inFlight=true
    const timer=setTimeout(()=>{timers.delete(timer);expired=true;row=null;publish()},30000)
    timers.add(timer)
    void env.request('/suggestion',{session_id:c.sessionId,stored_id:c.storedId}).then(result=>{
      clearTimeout(timer);timers.delete(timer)
      if(result.session_id!==c.sessionId||result.stored_id!==c.storedId) return
      if(expired){consumeLate(result.candidate);return}
      if(disposed) return
      const candidate=result.candidate
      if(!validRow(candidate)||candidate.root!==c.storedId) return
      const handled=ledger(storage)[key]
      if(handled?.version===candidate.version && handled.request_id===candidate.request_id) {
        if(['consumed','dismissed'].includes(handled.status)) acknowledge(handled)
        return
      }
      row=candidate;publish()
    }).catch(()=>{clearTimeout(timer);timers.delete(timer)}).finally(()=>{
      inFlight=false
      if(catchUpPending&&!row&&!expired&&!disposed){catchUpPending=false;started=false;start()}
    })
  }
  const off=env.onSettled(()=>{
    if(disposed||settledSeen) return
    settledSeen=true
    if(started&&!expired&&!row){
      if(inFlight) catchUpPending=true
      else {started=false;start()}
    }
  })
  return {
    update(next){state=next;publish();start()},
    refresh(){publish();start()},
    decide(status){
      const text=visible()
      if(!text||!['consumed','dismissed'].includes(status)) return null
      const d=decision(row,status)
      try {remember(storage,key,d)} catch {return null}
      row=null;publish();acknowledge(d)
      return text
    },
    dispose(){disposed=true;off();for(const timer of timers)clearTimeout(timer);timers.clear();row=null;env.publish(null)}
  }
}
// Inject only the documented SDK/React surface; shared with browser acceptance.
function createSettingsView({ jsx, useEffect, useRef, useState, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue }) {
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
      jsx('header', { children: [jsx('h2', { style: { fontSize: 20, fontWeight: 600 }, children: 'Prediction settings' }), jsx('p', { style: { color: 'var(--ui-text-secondary)' }, children: 'Neo Composer · suggestions stay drafts until you send them.' })] }),
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

const Settings = createSettingsView({ jsx, useEffect, useRef, useState, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue })
export default {
  id: 'neo-next-prompt',
  name: 'Neo Composer',
  version: '0.4.0',
  defaultEnabled: true,
  register(ctx) {
    ctx.register({ id: 'settings', area: ROUTES_AREA, data: { path: '/neo-composer' }, render: () => jsx(Settings, { ctx }) })
    ctx.register({ id: 'settings-nav', area: SIDEBAR_NAV_AREA, data: { path: '/neo-composer', label: 'Neo Composer', codicon: 'settings-gear' } })
    if (host.composer?.behaviorVersion !== 2) {
      ctx.register({ id: 'compatibility', area: 'statusBar.right', render: () => jsx('span', { title: 'Neo Composer requires composer behavior interface v2. No host files were changed.', children: 'Neo Composer · incompatible host' }) })
      host.notify({ kind: 'error', message: 'Neo Composer is disabled on this host. Install a compatible interface; no core files were changed by the plugin.' })
      return
    }
    ctx.register({ id: 'composer', area: 'composer.behavior.v2', data: {
      protocol: 2,
      create: env => createController(env, ctx.storage),
      keyAction,
      readOnlyKeys,
      lifecycle: event => profileLifecycle(ctx.storage, event)
    } })
  }
}
