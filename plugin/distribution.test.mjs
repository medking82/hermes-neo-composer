import test from 'node:test'
import assert from 'node:assert/strict'
import { registerHooks } from 'node:module'
import { readFileSync } from 'node:fs'
import { resolve,load } from './registration-stubs.mjs'
registerHooks({resolve,load})
const {host}=await import('@hermes/plugin-sdk')
const atom=value=>({get:()=>value,subscribe:()=>()=>{}})
const {default:plugin}=await import('../dist/plugin.js')

test('built distribution includes SDK suggestions and independent enhancement settings',()=>{
 const entries=[],pages=[]
 host.activeConnectionId=()=> 'fixture-connection'
 host.state={focusedSessionId:atom('runtime-fixture'),focusedStoredSessionId:atom('stored-fixture'),focusedSessionOwner:atom({connectionId:'fixture-connection',profile:'default'}),connectionId:atom('fixture-connection'),profile:atom('default'),busy:atom(false)}
 host.composer={getDraft:async()=>'',insertText:async()=>true,submit:()=>assert.fail('must never send')}
 plugin.register({storage:{get:(_key,fallback)=>fallback},register:entry=>{entries.push(entry);return()=>{}},registerSettingsPage:page=>{pages.push(page);return()=>{}}})
 assert.equal(entries.find(entry=>entry.id==='portable')?.area,'statusBar.right')
 const settings=pages[0].render(),tree=settings.type(settings.props)
 const extra=tree.props.children.filter(child=>typeof child?.type==='function').map(child=>child.type(child.props))
 assert.ok(extra.some(child=>child?.props?.['aria-label']==='Native Enhancement'))
 assert.equal(entries.some(entry=>entry.area==='composer.behavior.v2'),false)
 const source=readFileSync(new URL('../dist/plugin.js',import.meta.url),'utf8')
 assert.ok(!/node:child_process|window\.hermesDesktop|from ['"]node:/.test(source))
 const compatibility=JSON.parse(readFileSync(new URL('../dist/compatibility.json',import.meta.url),'utf8'))
 assert.equal(compatibility.sdk_mode.requires_strict_steering,false)
 assert.equal(compatibility.sdk_mode.auto_send,false)
})

test('CI discovers every plugin behavior and SDK regression suite',()=>{
 const workflow=readFileSync(new URL('../.github/workflows/test.yml',import.meta.url),'utf8')
 assert.match(workflow,/node --test plugin\/\*\.test\.mjs/)
})
