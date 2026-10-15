import test from 'node:test'
import assert from 'node:assert/strict'
import { createController, keyAction, readOnlyKeys } from './controller.mjs'
Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:()=>null}})

function fixture(overrides = {}) {
  const values = new Map(), requests = [], published = []
  let settled = () => {}
  const row = {root:'stored', version:'a'.repeat(64), request_id:'b'.repeat(32), status:'ready', text:'运行解析器回归测试'}
  const context = {connectionId:'ga401',profile:'default',sessionId:'runtime',storedId:'stored',busy:false}
  const env = {context, publish:v=>published.push(v), request:async(path,body)=>{requests.push({path,body});return {session_id:'runtime',stored_id:'stored',candidate:row}}, onSettled:fn=>{settled=fn;return()=>{settled=()=>{}}}, ...overrides}
  const storage = {get:(k,f)=>values.get(k) ?? f,set:(k,v)=>values.set(k,structuredClone(v))}
  const controller=createController(env,storage)
  return {controller,requests,published,storage,context,settled:()=>settled()}
}
const tick=()=>new Promise(r=>setImmediate(r))
test('queue and steer policy remains plugin-owned',()=>{
  assert.equal(keyAction({key:'Enter',busy:true}),'queue')
  assert.equal(keyAction({key:'Enter',busy:true,ctrlKey:true}),'steer')
  assert.equal(keyAction({key:'Enter',busy:false,ctrlKey:true}),undefined)
  assert.equal(keyAction({key:'Enter',busy:true,shiftKey:true}),undefined)
  assert.deepEqual(readOnlyKeys['composer.queue'],['enter'])
})
test('candidate is persistent, acceptance only returns a draft and never sends',async()=>{
  const f=fixture();f.controller.update({enabled:true,empty:true});await tick()
  assert.equal(f.published.at(-1),'运行解析器回归测试')
  assert.equal(f.controller.decide('consumed'),'运行解析器回归测试')
  assert.equal(f.published.at(-1),null)
  assert.deepEqual(f.requests.map(r=>r.path),['/suggestion','/decision'])
  assert.equal(Object.values(f.storage.get('decisions',{}))[0].status,'consumed')
})
test('typing and settled events do not refetch an already ready candidate',async()=>{
  const f=fixture();f.controller.update({enabled:true,empty:true});await tick()
  f.controller.update({enabled:true,empty:false});f.controller.update({enabled:true,empty:true});await tick()
  assert.equal(f.requests.length,1);f.settled();await tick();f.settled();await tick();assert.equal(f.requests.length,1)
})
test('dispose drops late results and stops event subscription',async()=>{
  let finish;const f=fixture({request:()=>new Promise(r=>finish=r)})
  f.controller.update({enabled:true,empty:true});f.controller.dispose()
  finish({session_id:'runtime',stored_id:'stored',candidate:{root:'stored',version:'a'.repeat(64),request_id:'b'.repeat(32),status:'ready',text:'不应显示的旧建议'}})
  await tick();assert.equal(f.published.at(-1),null);f.settled();assert.equal(f.published.at(-1),null)
})
test('blocked/busy/wrong-session/spoofed responses cannot publish',async()=>{
  const f=fixture();f.controller.update({enabled:false,empty:true});assert.equal(f.requests.length,0)
  const busy=fixture();busy.context.busy=true;busy.controller.update({enabled:true,empty:true});assert.equal(busy.requests.length,0)
  const g=fixture({request:async()=>({session_id:'other',stored_id:'stored',candidate:null})})
  g.controller.update({enabled:true,empty:true});await tick();assert.equal(g.published.at(-1),null)
  const spoof=fixture({request:async()=>({session_id:'runtime',stored_id:'stored',candidate:{root:'stored',version:'a'.repeat(64),request_id:'b'.repeat(32),status:'ready',text:'ab\u202ecd'}})})
  spoof.controller.update({enabled:true,empty:true});await tick();assert.equal(spoof.published.at(-1),null)
  spoof.controller.dispose()
})

test('late result records timeout, never fabricates a user dismissal',async t=>{
  t.mock.timers.enable({apis:['setTimeout']})
  let finish;const requests=[]
  const f=fixture({request:(path,body)=>{requests.push({path,body});return path==='/suggestion'?new Promise(r=>finish=r):Promise.resolve({recorded:true})}})
  f.controller.update({enabled:true,empty:true});t.mock.timers.tick(30001)
  finish({session_id:'runtime',stored_id:'stored',candidate:{root:'stored',version:'a'.repeat(64),request_id:'b'.repeat(32),status:'ready',text:'late candidate'}})
  await tick()
  assert.equal(f.published.at(-1),null)
  assert.equal(Object.values(f.storage.get('decisions',{}))[0].status,'timeout')
  assert.deepEqual(requests.map(r=>r.path),['/suggestion'])
  f.controller.dispose()
})
test('settled during flight coalesces; one catchup only if the first result is empty',async()=>{
  let finish;const requests=[]
  const f=fixture({request:(path,body)=>{requests.push({path,body});return new Promise(r=>finish=r)}})
  f.controller.update({enabled:true,empty:true});f.settled()
  assert.equal(requests.length,1)
  finish({session_id:'runtime',stored_id:'stored',candidate:null});await tick()
  assert.equal(requests.length,2)
  finish({session_id:'runtime',stored_id:'stored',candidate:null});await tick();f.settled()
  assert.equal(requests.length,2);f.controller.dispose()
})
test('empty result arms a bounded ten-minute retry that re-requests once',async t=>{
  t.mock.timers.enable({apis:['setTimeout']})
  const requests=[]
  const f=fixture({request:(path,body)=>{requests.push({path,body});return Promise.resolve({session_id:'runtime',stored_id:'stored',candidate:null})}})
  f.controller.update({enabled:true,empty:true});await tick()
  assert.equal(requests.length,1)
  t.mock.timers.tick(609999);await tick();assert.equal(requests.length,1,'no retry before the window')
  t.mock.timers.tick(2);await tick();assert.equal(requests.length,2,'one retry after the window')
  t.mock.timers.tick(610000);await tick();assert.equal(requests.length,3,'a still-empty retry re-arms the next window')
  f.controller.dispose()
})
test('typing, a ready row, or dispose cancels the retry timer',async t=>{
  t.mock.timers.enable({apis:['setTimeout']})
  const requests=[]
  const f=fixture({request:(path,body)=>{requests.push({path,body});return Promise.resolve({session_id:'runtime',stored_id:'stored',candidate:null})}})
  f.controller.update({enabled:true,empty:true});await tick()
  f.controller.update({enabled:true,empty:false})
  t.mock.timers.tick(610000);await tick();assert.equal(requests.length,1,'typing cancels the retry')
  f.controller.dispose()
  const g=fixture({request:(path,body)=>{requests.push({path,body});return Promise.resolve({session_id:'runtime',stored_id:'stored',candidate:null})}})
  g.controller.update({enabled:true,empty:true});await tick()
  g.controller.dispose()
  t.mock.timers.tick(610000);await tick();assert.equal(requests.length,2,'dispose cancels the retry')
})
