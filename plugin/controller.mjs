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
  // Backend re-asks a cached empty result only after 600s; arm the retry a
  // little past that gate so one request lands in the re-ask window.
  const EMPTY_RETRY_MS=610000
  let disposed=false,expired=false,started=false,settledSeen=false,inFlight=false,catchUpPending=false,row=null,state={enabled:false,empty:false},retryTimer=null,phase='idle'
  const visible=()=>!disposed&&!expired&&!c.busy&&state.enabled&&state.empty&&validRow(row) ? row.text : null
  const publish=()=>env.publish(visible(),phase)
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
    started=true;inFlight=true;phase='generating';publish()
    const timer=setTimeout(()=>{timers.delete(timer);expired=true;row=null;phase='timeout';publish()},30000)
    timers.add(timer)
    void env.request('/suggestion',{session_id:c.sessionId,stored_id:c.storedId}).then(result=>{
      clearTimeout(timer);timers.delete(timer)
      if(result.session_id!==c.sessionId||result.stored_id!==c.storedId) {
        if(!disposed&&!expired){phase='stale';publish()}
        return
      }
      if(expired){consumeLate(result.candidate);return}
      if(disposed) return
      const candidate=result.candidate
      if(!validRow(candidate)||candidate.root!==c.storedId){
        // A null/empty result re-asks itself once the backend's empty-retry
        // window is open, unless this version already has a user decision.
        const settled=ledger(storage)[key]
        const decided=candidate && typeof candidate==='object'
          && settled?.version===candidate.version && settled.request_id===candidate.request_id
        const bound=candidate && !Array.isArray(candidate) && candidate.root===c.storedId
          && /^[a-f0-9]{64}$/.test(candidate.version) && /^[a-f0-9]{32}$/.test(candidate.request_id)
        const returnedPhase=candidate==null?'empty':candidate.root!==c.storedId?'stale':!bound?'failed':
          ({__proto__:null,empty:'empty',error:'failed',timeout:'timeout',pending:'pending',stale:'stale',consumed:'consumed',dismissed:'dismissed'}[candidate.status]||'failed')
        if(decided){phase=bound&&['consumed','dismissed','timeout'].includes(settled.status)?settled.status:returnedPhase;publish();return}
        phase=returnedPhase;publish()
        armRetry()
        return
      }
      const handled=ledger(storage)[key]
      if(handled?.version===candidate.version && handled.request_id===candidate.request_id) {
        if(['consumed','dismissed'].includes(handled.status)) acknowledge(handled)
        phase=['consumed','dismissed','timeout'].includes(handled.status)?handled.status:'empty';publish()
        return
      }
      cancelRetry()
      row=candidate;phase='ready';publish()
    }).catch(()=>{
      clearTimeout(timer);timers.delete(timer)
      if(!disposed&&!expired){phase='failed';publish()}
    }).finally(()=>{
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
        validate:async()=> {
          const result=await env.request('/validate',{
            session_id:c.sessionId,stored_id:c.storedId,version:candidate.version,request_id:candidate.request_id
          })
          if(result?.current===true) return true
          if(row===candidate) {expired=true;row=null;phase='stale';cancelRetry();publish()}
          return false
        },
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
            phase='consumed'
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
      row=null;phase=status;publish();acknowledge(d)
      return text
    },
    dispose(){disposed=true;off();for(const timer of timers)clearTimeout(timer);timers.clear();row=null;env.publish(null)}
  }
}
