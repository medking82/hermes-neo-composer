import { host, useValue, Popover, PopoverTrigger, PopoverContent, ROUTES_AREA, SIDEBAR_NAV_AREA, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@hermes/plugin-sdk'
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
  // Backend re-asks a cached empty result only after 600s; arm the retry a
  // little past that gate so one request lands in the re-ask window.
  const EMPTY_RETRY_MS=610000
  let disposed=false,expired=false,started=false,settledSeen=false,inFlight=false,catchUpPending=false,row=null,state={enabled:false,empty:false},retryTimer=null
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
  const cancelRetry=()=>{if(retryTimer){clearTimeout(retryTimer);timers.delete(retryTimer);retryTimer=null}}
  const armRetry=()=>{
    if(retryTimer||disposed||expired) return
    retryTimer=setTimeout(()=>{
      timers.delete(retryTimer);retryTimer=null
      if(disposed||expired||c.busy||!state.enabled||!state.empty||row||inFlight) return
      started=false
      start()
    },EMPTY_RETRY_MS)
    timers.add(retryTimer)
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
      if(!validRow(candidate)||candidate.root!==c.storedId){
        // A null/empty result re-asks itself once the backend's empty-retry
        // window is open, unless this version already has a user decision.
        const settled=ledger(storage)[key]
        const decided=candidate && typeof candidate==='object'
          && settled?.version===candidate.version && settled.request_id===candidate.request_id
        if(decided) return
        armRetry()
        return
      }
      const handled=ledger(storage)[key]
      if(handled?.version===candidate.version && handled.request_id===candidate.request_id) {
        if(['consumed','dismissed'].includes(handled.status)) acknowledge(handled)
        return
      }
      cancelRetry()
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
    capture(){
      const text=visible(), candidate=row
      if(!text) return null
      let prior
      try {prior=JSON.stringify(ledger(storage)[key])} catch {return null}
      let committed=false
      return Object.freeze({
        text,
        current:()=>row===candidate && visible()===text,
        commit(){
          if(committed) return true
          try {
            // An insert can finish after the component unmounts. Bind its
            // decision to the captured owner, but never erase a later choice.
            if(JSON.stringify(ledger(storage)[key])!==prior) return false
            const d=decision(candidate,'consumed')
            remember(storage,key,d)
            committed=true
            if(row===candidate) row=null
            if(!disposed) publish()
            acknowledge(d)
            return true
          } catch {return false}
        }
      })
    },
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
// SDK-only mode: explicit preview and acknowledged insertion, never send.
const portableAtoms = ['focusedSessionId','focusedStoredSessionId','focusedSessionOwner','connectionId','profile','busy']
const portableSupported = host => typeof host.activeConnectionId==='function' && typeof host.composer?.getDraft==='function' && typeof host.composer?.insertText==='function' && portableAtoms.every(key=>typeof host.state?.[key]?.get==='function')
function readPortableContext(host) {
  if(!portableSupported(host)) return null
  const read=key=>host.state[key].get()
  const connectionId=host.activeConnectionId(), sessionId=read('focusedSessionId'), storedId=read('focusedStoredSessionId'), busy=read('busy')
  const rawProfile=read('profile'), owner=read('focusedSessionOwner')
  const profile=typeof rawProfile==='string'?(rawProfile||'default'):null
  if(!owner || Array.isArray(owner) || typeof owner!=='object' || !profile || typeof owner.profile!=='string') return null
  if(![connectionId,sessionId,storedId].every(value=>typeof value==='string' && value.length>0) || typeof busy!=='boolean') return null
  if(connectionId!==owner.connectionId || profile!==(owner.profile||'default')) return null
  return Object.freeze({connectionId,profile,sessionId,storedId,busy})
}
const samePortableContext = (host,context) => !!context && JSON.stringify(readPortableContext(host))===JSON.stringify(context)
const portableOwnerMatches = (host,context) => host.activeConnectionId()===context.connectionId && (host.state.profile.get()||'default')===context.profile
async function insertPortableOffer(host,context,controller) {
  if(!context || context.busy || !samePortableContext(host,context)) return {ok:false,reason:'Context Changed'}
  const offer=controller?.capture()
  if(!offer) return {ok:false,reason:'Suggestion Is No Longer Available'}
  const draft=await host.composer.getDraft(context.storedId)
  if(draft!=='' || !samePortableContext(host,context) || !offer.current()) return {ok:false,reason:'Draft Or Context Changed'}
  const applied=await host.composer.insertText(context.storedId,offer.text,{mode:'inline'})
  if(applied!==true) return {ok:false,reason:'Draft Was Not Inserted'}
  return {ok:true,durable:offer.commit()}
}
function createPortableSession({host,ctx,context,createController,onChange}) {
  let disposed=false,started=false,controller=null,inserting=false
  const current=()=>!disposed && !!context && !context.busy && samePortableContext(host,context)
  const publish=update=>{if(current()) onChange(update)}
  const request=async(path,body)=>{
    if(path==='/decision') {
      if(!portableOwnerMatches(host,context)) throw Error('Owner Changed')
    } else {
      if(!current() || await host.composer.getDraft(context.storedId)!=='' || !current()) throw Error('Draft Or Context Changed')
    }
    const result=await ctx.rest(path,{method:'POST',body})
    if(path!=='/decision' && !current()) throw Error('Context Changed')
    return result
  }
  return {
    async start(){
      if(started || !current()) return
      started=true;publish({phase:'checking',text:null})
      try {
        const view=await ctx.rest('/settings')
        if(!current()) return
        if(view?.settings?.enabled!==true || !view?.selection?.route) {publish({phase:'paused',text:null});return}
        if(await host.composer.getDraft(context.storedId)!=='' || !current()) {publish({phase:'draft',text:null});return}
        controller=createController({context,request,publish:text=>publish({phase:text?'ready':'idle',text}),onSettled:listener=>typeof ctx.onEvent==='function'?ctx.onEvent('session.info',event=>{
          if(current() && event.session_id===context.sessionId && event.payload?.running===false) listener()
        }):()=>{}},ctx.storage)
        controller.update({enabled:true,empty:true})
      } catch {publish({phase:'unavailable',text:null})}
    },
    async insert(){
      if(inserting) return {ok:false,reason:'Insertion Already Pending'}
      inserting=true
      try {return await insertPortableOffer(host,context,controller)}
      catch {return {ok:false,reason:'Insertion Could Not Be Confirmed'}}
      finally {inserting=false}
    },
    dismiss(){return current() && !!controller?.decide('dismissed')},
    dispose(){disposed=true;controller?.dispose()}
  }
}
function createPortableWidget({host,jsx,useValue,useEffect,useRef,useState,Button,Popover,PopoverTrigger,PopoverContent,createController}) {
  return function PortableSuggestions({ctx}) {
    useValue(host.state.focusedSessionId)
    useValue(host.state.focusedStoredSessionId)
    useValue(host.state.focusedSessionOwner)
    useValue(host.state.connectionId)
    useValue(host.state.profile)
    useValue(host.state.busy)
    const [open,setOpen]=useState(false), [revision,setRevision]=useState(0), [view,setView]=useState({phase:'idle',text:null}), [notice,setNotice]=useState(''), [pending,setPending]=useState(false)
    const ref=useRef(null), context=readPortableContext(host), key=JSON.stringify(context)
    useEffect(()=>{
      setView({phase:'idle',text:null});setNotice('');setPending(false)
      if(!open || !context || context.busy) return
      const session=createPortableSession({host,ctx,context,createController,onChange:setView})
      ref.current=session;void session.start()
      return ()=>{if(ref.current===session)ref.current=null;session.dispose()}
    },[ctx,open,key,revision])
    const insert=async()=>{
      const session=ref.current;if(!session || pending)return
      setPending(true);setNotice('')
      const result=await session.insert()
      if(ref.current!==session)return
      setPending(false);setNotice(result.ok?(result.durable?'Inserted As Draft':'Inserted As Draft; Decision Was Not Saved'):result.reason)
    }
    const hints={checking:'Checking Prediction Settings…',paused:'Prediction Is Paused. Check Neo Composer Settings.',draft:'Keep The Draft Empty To Request A Suggestion.',idle:'No Suggestion For This Context Yet.',unavailable:'Prediction Backend Is Unavailable.'}
    return jsx(Popover,{open,onOpenChange:setOpen,children:[
      jsx(PopoverTrigger,{asChild:true,children:jsx(Button,{variant:'ghost',size:'sm','aria-label':'Neo Composer Suggestions',children:'Neo Composer · Suggestions'})}),
      jsx(PopoverContent,{align:'end',style:{width:340,maxWidth:'calc(100vw - 24px)',display:'grid',gap:12},children:[
        jsx('strong',{children:'Neo Composer Suggestions'}),
        jsx('p',{style:{color:'var(--ui-text-secondary)'},children:'SDK Compatibility Mode · Native Shortcuts Are Unchanged'}),
        jsx('p',{role:'status',style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'},children:!context?'Select A Chat Owned By The Active Gateway.':context.busy?'Suggestions Pause While The Chat Is Working.':view.text||hints[view.phase]||hints.idle}),
        jsx('div',{style:{display:'flex',flexWrap:'wrap',gap:8},children:[
          jsx(Button,{disabled:!view.text||pending||!context||context.busy,onClick:insert,children:pending?'Inserting…':'Insert As Draft'}),
          jsx(Button,{variant:'outline',disabled:!view.text||pending,onClick:()=>{if(ref.current?.dismiss())setNotice('Dismissed For This Context')},children:'Dismiss'}),
          jsx(Button,{variant:'ghost',disabled:pending,onClick:()=>setRevision(value=>value+1),children:'Refresh'})
        ]}),
        jsx('p',{role:'status',style:{color:'var(--ui-text-secondary)'},children:notice})
      ]})
    ]})
  }
}
// Local launch is an explicit user gesture. No backend shell or process API.
const installerKey='enhancement.installerPath'
function validInstallerPath(value) {
  if(typeof value!=='string' || value.length>1024 || !/^[A-Za-z]:[\\/]/.test(value) || /[\x00-\x1f<>"|?*:%!]/.test(value.slice(2))) return false
  const parts=value.slice(3).split(/[\\/]/)
  if(parts.some(part=>!part || part==='.' || part==='..' || /[. ]$/.test(part) || /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(part))) return false
  return /^NeoComposerSetup\.cmd$/i.test(parts.at(-1))
}
async function chooseEnhancementInstaller(ctx) {
  if(typeof ctx.os?.pickOpenPath!=='function') return {ok:false,reason:'Local File Picker Is Unavailable'}
  try {
    const path=await ctx.os.pickOpenPath({title:'Select The Trusted Neo Composer Installer',filters:[{name:'Neo Composer Installer',extensions:['cmd']}]})
    if(path===null) return {ok:false,reason:'Selection Cancelled'}
    if(!validInstallerPath(path)) return {ok:false,reason:'Choose A Local NeoComposerSetup.cmd File'}
    ctx.storage.set(installerKey,path)
    if(ctx.storage.get(installerKey,null)!==path) return {ok:false,reason:'Installer Selection Was Not Saved'}
    return {ok:true,path}
  } catch {return {ok:false,reason:'Installer Selection Could Not Be Saved'}}
}
async function launchEnhancementInstaller(ctx,mode='apply') {
  const names={apply:'NeoComposerSetup.cmd',check:'NeoComposerCheck.cmd',rollback:'NeoComposerUninstall.cmd'}
  if(!Object.hasOwn(names,mode)) return {ok:false,reason:'Unsupported Installer Action'}
  try {
    const saved=ctx.storage.get(installerKey,null)
    if(!validInstallerPath(saved)) return {ok:false,reason:'Select A Trusted Local Installer First'}
    if(typeof ctx.os?.openExternal!=='function') return {ok:false,reason:'Local Launch Is Unavailable'}
    const path=saved.replace(/NeoComposerSetup\.cmd$/i,names[mode])
    if(await ctx.os.openExternal(path)!==true) return {ok:false,reason:'Installer Open Request Failed'}
    // The SDK acknowledges an open request, NOT process exit or installation.
    return {ok:true,state:'requested',installed:false}
  } catch {return {ok:false,reason:'Installer Open Request Failed'}}
}
function createEnhancementView({host,jsx,useRef,useState,Button,portableSupported}) {
  return function EnhancementSettings({ctx}) {
    const [path,setPath]=useState(()=>{try{return ctx.storage.get(installerKey,'')}catch{return ''}})
    const [notice,setNotice]=useState(''), [busy,setBusy]=useState(false), pending=useRef(false)
    const operate=async action=>{
      if(pending.current)return
      pending.current=true;setBusy(true);setNotice('')
      try {
        const result=action==='choose'?await chooseEnhancementInstaller(ctx):await launchEnhancementInstaller(ctx,action)
        if(result.path)setPath(result.path)
        setNotice(result.ok?(action==='choose'?'Installer Selected. Launch Only A Package You Trust.':'Open Request Sent. Check The Installer Result; Installation Is Not Yet Confirmed.'):result.reason)
      } finally {pending.current=false;setBusy(false)}
    }
    const native=host.composer?.behaviorVersion===2, strict=native && host.composer?.strictSteeringVersion===1
    return jsx('section',{'aria-label':'Native Enhancement',style:{display:'grid',gap:12,padding:16,border:'1px solid var(--ui-stroke-secondary)',borderRadius:8},children:[
      jsx('h3',{style:{fontWeight:600},children:'Native Enhancement'}),
      jsx('p',{children:native?'Native Suggestions: Loaded':portableSupported(host)?'SDK Suggestions: Available · Native Enhancement: Not Loaded':'Suggestions: Host Support Required'}),
      jsx('p',{style:{color:'var(--ui-text-secondary)'},children:strict?'Strict Steering UI: Present — Backend Support Still Requires Verification':'Strict Steering UI: Not Present · Native Shortcuts Are Unchanged'}),
      jsx('p',{style:{color:'var(--ui-text-secondary)'},children:'One-Time Setup: Select NeoComposerSetup.cmd From Your Trusted Enhancement Package. Future Actions Use That Local Installer, Not The Remote Agent Backend.'}),
      jsx('code',{style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'},children:path||'No Local Installer Selected'}),
      jsx('div',{style:{display:'flex',flexWrap:'wrap',gap:8},children:[
        jsx(Button,{variant:'outline',disabled:busy||typeof ctx.os?.pickOpenPath!=='function',onClick:()=>operate('choose'),children:'Select Local Installer'}),
        jsx(Button,{disabled:busy||!validInstallerPath(path)||typeof ctx.os?.openExternal!=='function',onClick:()=>operate('apply'),children:'Install / Repair'}),
        jsx(Button,{variant:'outline',disabled:busy||!validInstallerPath(path)||typeof ctx.os?.openExternal!=='function',onClick:()=>operate('check'),children:'Check Installation'}),
        jsx(Button,{variant:'ghost',disabled:busy||!validInstallerPath(path)||typeof ctx.os?.openExternal!=='function',onClick:()=>operate('rollback'),children:'Uninstall Enhancement'})
      ]}),
      jsx('p',{role:'status',style:{color:'var(--ui-text-secondary)'},children:notice}),
      jsx('p',{style:{fontSize:12,color:'var(--ui-text-secondary)'},children:'Unknown Hermes Versions Are Refused. No Forced Restart, Downgrade Or Automatic Patching. Opening The Installer Does Not Prove It Finished.'})
    ]})
  }
}
// Inject only the documented SDK/React surface; shared with browser acceptance.
function createSettingsView({ jsx, useEffect, useRef, useState, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Enhancement }) {
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
      typeof Enhancement === 'function' ? jsx(Enhancement, { ctx }) : null,
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

const Enhancement = createEnhancementView({ host, jsx, useRef, useState, Button, portableSupported })
const PortableSuggestions = createPortableWidget({ host, jsx, useValue, useEffect, useRef, useState, Button, Popover, PopoverTrigger, PopoverContent, createController })
const Settings = createSettingsView({ jsx, useEffect, useRef, useState, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Enhancement })
export default {
  id: 'neo-next-prompt',
  name: 'Neo Composer',
  version: '0.5.0-rc.1',
  defaultEnabled: true,
  register(ctx) {
    if (typeof ctx.registerSettingsPage === 'function') {
      // Settings live in Settings ▸ Plugins (the host's unified plugin home); no sidebar row of its own.
      ctx.registerSettingsPage({ id: 'settings', title: 'Neo Composer', icon: 'settings-gear', render: () => jsx(Settings, { ctx }) })
    } else {
      // Hosts without the unified settings surface keep the legacy page + sidebar row,
      // so the prediction settings stay reachable instead of silently disappearing.
      ctx.register({ id: 'settings', area: ROUTES_AREA, data: { path: '/neo-composer' }, render: () => jsx(Settings, { ctx }) })
      ctx.register({ id: 'settings-nav', area: SIDEBAR_NAV_AREA, data: { path: '/neo-composer', label: 'Neo Composer', codicon: 'settings-gear' } })
    }
    if (host.composer?.behaviorVersion !== 2) {
      if (portableSupported(host)) {
        ctx.register({ id: 'portable', area: 'statusBar.right', render: () => jsx(PortableSuggestions, { ctx }) })
      } else {
        ctx.register({ id: 'compatibility', area: 'statusBar.right', render: () => jsx('span', { title: 'Native enhancement or owner-aware draft SDK is required. Settings and enhancement setup remain available.', children: 'Neo Composer · Suggestions Unavailable' }) })
        host.notify({ kind: 'error', message: 'Neo Composer suggestions require a compatible draft SDK or native enhancement. Settings remain available; no core files were changed.' })
      }
      return
    }
    const strict = host.composer.strictSteeringVersion === 1
    ctx.register({ id: 'composer', area: 'composer.behavior.v2', data: {
      protocol: 2,
      create: env => createController(env, ctx.storage),
      keyAction: strict ? keyAction : () => undefined,
      readOnlyKeys: strict ? readOnlyKeys : {},
      lifecycle: event => profileLifecycle(ctx.storage, event)
    } })
    if (!strict) ctx.register({ id: 'steering-unavailable', area: 'statusBar.right', render: () => jsx('span', { title: 'Suggestions are enabled. Strict Steering and Neo key overrides are unavailable; native shortcuts are unchanged.', children: 'Neo Composer · Suggestions Only' }) })
  }
}
