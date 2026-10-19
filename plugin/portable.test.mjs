import test from 'node:test'
import assert from 'node:assert/strict'
import { readPortableContext, samePortableContext, insertPortableOffer, createPortableSession } from './portable.mjs'
import { createController } from './controller.mjs'
Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:()=>null}})

function fixture() {
  const values = {focusedSessionId:'runtime', focusedStoredSessionId:'stored', focusedSessionOwner:{connectionId:'fixture-host',profile:'default'}, connectionId:'fixture-host', profile:'default', busy:false}
  const inserted = [], calls = [], updates = [], saved = new Map()
  const host = {activeConnectionId:()=>values.connectionId,state:Object.fromEntries(Object.keys(values).map(key=>[key,{get:()=>values[key]}])),composer:{getDraft:async()=>'',insertText:async(...args)=>{inserted.push(args);return true}}}
  const candidate = {root:'stored',version:'a'.repeat(64),request_id:'b'.repeat(32),status:'ready',text:'Review The Tests'}
  const ctx = {storage:{get:(k,f)=>saved.get(k)??f,set:(k,v)=>saved.set(k,structuredClone(v))},onEvent:()=>()=>{},rest:async(path,opts)=>{calls.push([path,opts]);if(path==='/settings')return {settings:{enabled:true},selection:{route:{provider:'fixture-provider',model:'fixture-model'}}};if(path==='/validate')return {current:true};return {session_id:'runtime',stored_id:'stored',candidate}}}
  return {host,ctx,values,inserted,calls,updates,saved,candidate}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve))

test('portable context binds exact connection, profile, runtime and stored session',()=>{
  const f=fixture(), c=readPortableContext(f.host)
  assert.deepEqual(c,{connectionId:'fixture-host',profile:'default',sessionId:'runtime',storedId:'stored',busy:false})
  assert.ok(samePortableContext(f.host,c))
  f.values.focusedSessionOwner={connectionId:'other',profile:'default'}
  assert.equal(readPortableContext(f.host),null)
  f.values.focusedSessionOwner={connectionId:'fixture-host',profile:'another-profile'}
  assert.equal(readPortableContext(f.host),null)
  f.values.focusedSessionOwner=null
  assert.equal(readPortableContext(f.host),null)
})

test('an insertion never sends and commits only the acknowledged draft write',async()=>{
  const f=fixture(), events=[]
  const controller={capture:()=>({text:'Review The Tests',current:()=>true,validate:async()=>true,commit:()=>{events.push('commit');return true}})}
  f.host.composer.insertText=async(...args)=>{events.push('insert');f.inserted.push(args);return true}
  assert.deepEqual(await insertPortableOffer(f.host,readPortableContext(f.host),controller),{ok:true,durable:true})
  assert.deepEqual(events,['insert','commit'])
  assert.deepEqual(f.inserted,[['stored','Review The Tests',{mode:'inline'}]])
  assert.equal(f.host.composer.submit,undefined)
})

test('failed insertion does not consume the candidate',async()=>{
  const f=fixture();let commits=0
  f.host.composer.insertText=async()=>false
  const controller={capture:()=>({text:'text',current:()=>true,validate:async()=>true,commit:()=>{commits++;return true}})}
  assert.equal((await insertPortableOffer(f.host,readPortableContext(f.host),controller)).ok,false)
  assert.equal(commits,0)
})

test('changed drafts and context switches during draft read refuse insertion',async()=>{
  for(const change of ['draft','connection','profile','runtime','stored','busy']) {
    const f=fixture(), c=readPortableContext(f.host)
    f.host.composer.getDraft=async()=>{
      if(change==='connection')f.values.connectionId='other'
      if(change==='profile')f.values.profile='other'
      if(change==='runtime')f.values.focusedSessionId='other'
      if(change==='stored')f.values.focusedStoredSessionId='other'
      if(change==='busy')f.values.busy=true
      return change==='draft'?'User Draft':''
    }
    const controller={capture:()=>({text:'text',current:()=>true,commit:()=>assert.fail('must not consume')})}
    assert.equal((await insertPortableOffer(f.host,c,controller)).ok,false,change)
    assert.deepEqual(f.inserted,[],change)
  }
})

test('portable session uses the existing controller, settings and persisted decisions',async()=>{
  const f=fixture(), c=readPortableContext(f.host)
  const session=createPortableSession({host:f.host,ctx:f.ctx,context:c,createController,onChange:update=>f.updates.push(update)})
  await session.start();await tick()
  assert.equal(f.updates.at(-1).text,'Review The Tests')
  assert.equal((await session.insert()).ok,true)
  assert.equal(Object.values(f.saved.get('decisions'))[0].status,'consumed')
  assert.deepEqual(f.calls.map(call=>call[0]),['/settings','/suggestion','/validate','/decision'])
  session.dispose()
})

test('disabled prediction or a nonempty draft produces no generation call',async()=>{
  for(const mode of ['disabled','draft','unmounted']) {
    const f=fixture()
    if(mode==='disabled')f.ctx.rest=async path=>{f.calls.push([path]);return {settings:{enabled:false},selection:{route:null}}}
    else f.host.composer.getDraft=async()=>mode==='draft'?'Draft':null
    const session=createPortableSession({host:f.host,ctx:f.ctx,context:readPortableContext(f.host),createController,onChange:()=>{}})
    await session.start();await tick();session.dispose()
    assert.ok(!f.calls.some(call=>call[0]==='/suggestion'),mode)
  }
})

test('switching owner while settings loads prevents generation and stale publication',async()=>{
  const f=fixture();let finish
  f.ctx.rest=path=>{f.calls.push([path]);return new Promise(resolve=>{finish=resolve})}
  const session=createPortableSession({host:f.host,ctx:f.ctx,context:readPortableContext(f.host),createController,onChange:update=>f.updates.push(update)})
  const loading=session.start();f.values.connectionId='another-host'
  finish({settings:{enabled:true},selection:{route:{}}});await loading;await tick()
  assert.ok(!f.calls.some(call=>call[0]==='/suggestion'))
  assert.ok(!f.updates.some(update=>update.text))
  session.dispose()
})

test('a model or provider route change rejects the cached offer without regeneration or insertion',async()=>{
  const f=fixture(), original=f.ctx.rest
  let current=true
  f.ctx.rest=async(path,options)=>{
    if(path==='/validate') {f.calls.push([path,options]);return {current}}
    return original(path,options)
  }
  const session=createPortableSession({host:f.host,ctx:f.ctx,context:readPortableContext(f.host),createController,onChange:update=>f.updates.push(update)})
  try {
    await session.start();await tick()
    assert.equal(f.updates.at(-1).text,f.candidate.text)
    current=false
    assert.equal((await session.insert()).ok,false)
    assert.equal(f.updates.at(-1).text,null)
    assert.deepEqual(f.inserted,[])
    assert.equal(f.calls.filter(([path])=>path==='/suggestion').length,1)
    assert.ok(!f.calls.some(([path])=>path==='/decision'))
    assert.deepEqual(f.calls.find(([path])=>path==='/validate')[1].body,{
      session_id:'runtime',stored_id:'stored',version:f.candidate.version,request_id:f.candidate.request_id
    })
  } finally {session.dispose()}
})

test('validation errors, malformed results and owner/draft changes cannot insert or consume',async()=>{
  for(const mode of ['error','malformed','profile','connection','runtime','stored','busy','draft']) {
    const f=fixture(), original=f.ctx.rest
    let draft=''
    f.host.composer.getDraft=async()=>draft
    f.ctx.rest=async(path,options)=>{
      if(path==='/validate') {
        f.calls.push([path,options])
        if(mode==='error') throw Error('fixture validation unavailable')
        if(mode==='malformed') return {current:'true'}
        if(mode==='profile')f.values.profile='other-profile'
        if(mode==='connection')f.values.connectionId='other-connection'
        if(mode==='runtime')f.values.focusedSessionId='other-runtime'
        if(mode==='stored')f.values.focusedStoredSessionId='other-stored'
        if(mode==='busy')f.values.busy=true
        if(mode==='draft')draft='Preserved User Draft'
        return {current:true}
      }
      return original(path,options)
    }
    const session=createPortableSession({host:f.host,ctx:f.ctx,context:readPortableContext(f.host),createController,onChange:update=>f.updates.push(update)})
    try {
      await session.start();await tick()
      assert.equal((await session.insert()).ok,false,mode)
      assert.deepEqual(f.inserted,[],mode)
      assert.equal(f.calls.filter(([path])=>path==='/suggestion').length,1,mode)
      assert.ok(!f.calls.some(([path])=>path==='/decision'),mode)
      if(mode==='draft')assert.equal(draft,'Preserved User Draft')
    } finally {session.dispose()}
  }
})
