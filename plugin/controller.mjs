// Portable plugin policy: no app-private imports, DOM handlers, tools or auto-send.
export const readOnlyKeys = {'composer.queue':['enter'],'composer.steer':['mod+enter']}
export function keyAction(e) {
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
export function profileLifecycle(storage,event) {
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
export function createController(env,storage) {
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
