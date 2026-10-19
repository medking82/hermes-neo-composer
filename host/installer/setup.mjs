// User-launched, local-only dispatcher over the existing fixed-release transaction.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { createHash, randomUUID } from 'node:crypto'
import { execFileSync, spawnSync } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'
const here=path.dirname(fileURLToPath(import.meta.url))
const tools=['install.mjs','compat.mjs','backend.mjs','setup.mjs']
const modes=['check','apply','rollback']
const digest=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex')
function plainDirectory(directory,create=false){
 const resolved=path.resolve(directory)
 for(let item=resolved;;item=path.dirname(item)){
  if(fs.existsSync(item)){const stat=fs.lstatSync(item);assert(stat.isDirectory()&&!stat.isSymbolicLink(),'Linked Or Non-Directory Installer Path')}
  if(path.dirname(item)===item)break
 }
 if(create)fs.mkdirSync(resolved,{recursive:true,mode:0o700})
 return resolved
}
function contained(base,relative){
 assert(typeof relative==='string' && relative.length>0 && !relative.includes('\\') && !relative.includes(':') && !path.isAbsolute(relative),'Unsafe Package Directory')
 const parts=relative.split('/');assert(parts.every(part=>part && part!=='.' && part!=='..'),'Unsafe Package Directory')
 plainDirectory(base)
 let item=base
 for(const part of parts){item=path.join(item,part);const info=fs.lstatSync(item);assert(!info.isSymbolicLink(),'Linked Installer Payload')}
 return item
}
function readJson(file){assert(fs.lstatSync(file).isFile() && fs.statSync(file).size<=1024*1024,'Invalid Installer Metadata');return JSON.parse(fs.readFileSync(file,'utf8'))}
const headOf=root=>execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim()
function releaseFor(setupDir,catalog,head){
 assert(catalog.schema===1 && Array.isArray(catalog.packages),'Invalid Installer Catalog')
 for(const entry of catalog.packages){
  assert(typeof entry.id==='string' && /^[a-z0-9][a-z0-9-]{0,79}$/.test(entry.id),'Invalid Enhancement Id')
  assert(typeof entry.directory==='string' && entry.directory===`packages/${entry.id}`,'Unsafe Package Directory')
  assert(Array.isArray(entry.heads) && entry.heads.length>0 && new Set(entry.heads).size===entry.heads.length && entry.heads.every(value=>typeof value==='string' && /^[a-f0-9]{40}$/.test(value)),'Invalid Desktop Revision')
  assert(typeof entry.releaseSha256==='string' && /^[a-f0-9]{64}$/.test(entry.releaseSha256),'Invalid Release Digest')
 }
 const matching=catalog.packages.filter(entry=>entry.heads.includes(head))
 assert(matching.length>0,`Unsupported Host Version ${head}. SDK Suggestions Remain Available; No Old Package Was Applied.`)
 assert.equal(matching.length,1,'Ambiguous Enhancement Packages')
 const entry=matching[0],bundle=contained(setupDir,entry.directory),release=contained(bundle,'release.json')
 assert.equal(digest(release),entry.releaseSha256,'Release Integrity Mismatch')
 const manifest=readJson(release)
 assert.deepEqual([...manifest.roles.desktop.heads].sort(),[...entry.heads].sort(),'Catalog And Release Revisions Differ')
 assert(catalog.tools && typeof catalog.tools==='object' && !Array.isArray(catalog.tools),'Missing Installer Tool Digests')
 assert.deepEqual(Object.keys(catalog.tools).sort(),[...tools].sort(),'Unexpected Installer Tools')
 for(const name of tools){assert(/^[a-f0-9]{64}$/.test(catalog.tools[name]),'Invalid Tool Digest');assert.equal(digest(contained(setupDir,name)),catalog.tools[name],'Tool Integrity Mismatch: '+name)}
 return {bundle,entry}
}
function acquire(lockDir,root){
 plainDirectory(lockDir,true)
 const key=createHash('sha256').update(process.platform==='win32'?fs.realpathSync(root).toLowerCase():fs.realpathSync(root)).digest('hex')
 const file=path.join(lockDir,key+'.lock'),owner=JSON.stringify({pid:process.pid,nonce:randomUUID(),root})
 let fd
 try{fd=fs.openSync(file,'wx',0o600)}catch(error){if(error.code==='EEXIST')throw Error('Installer Already Running Or Previous Transaction Needs Inspection');throw error}
 try{fs.writeFileSync(fd,owner)}catch(error){fs.closeSync(fd);throw error}
 return ()=>{fs.closeSync(fd);assert(!fs.lstatSync(file).isSymbolicLink() && fs.readFileSync(file,'utf8')===owner,'Installer Lock Ownership Changed');fs.unlinkSync(file)}
}
function invoke(setupDir,mode,root,bundle){
 const child=spawnSync(process.execPath,[path.join(setupDir,'install.mjs'),mode,root,bundle],{encoding:'utf8',maxBuffer:8*1024*1024,windowsHide:true})
 if(child.error || child.status===null)throw Error('Installer Outcome Unknown; Inspect The Existing Receipt Before Retrying')
 if(child.status!==0)return {ok:false,exit:child.status,error:(child.stderr||child.stdout||'Installer Failed').slice(-8000)}
 let result
 try{result=JSON.parse(child.stdout)}catch{throw Error('Installer Receipt Was Not Valid JSON')}
 const expected=mode==='check'?['ready','already_installed']:mode==='apply'?['installed','already_installed']:['rolled_back']
 assert(expected.includes(result.state) && result.verified===true,'Installer Did Not Verify The Requested State')
 return {ok:true,result}
}
export function runSetup({setupDir=here,mode,lockDir}={}){
 assert(modes.includes(mode),'Use Only check, apply Or rollback; No Force Options')
 const catalog=readJson(contained(setupDir,'catalog.json'))
 const defaultRoot=process.env.LOCALAPPDATA?path.join(process.env.LOCALAPPDATA,'hermes','hermes-agent'):null
 assert(typeof (catalog.desktopRoot??defaultRoot)==='string' && path.isAbsolute(catalog.desktopRoot??defaultRoot),'Desktop Root Must Be An Absolute Local Path')
 const root=plainDirectory(catalog.desktopRoot??defaultRoot),head=headOf(root)
 const {bundle,entry}=releaseFor(setupDir,catalog,head)
 const locks=lockDir??path.join(process.env.LOCALAPPDATA||path.join(os.homedir(),'.local','state'),'NeoComposer','InstallerLocks')
 const release=acquire(locks,root)
 try{
  assert.equal(headOf(root),head,'Desktop Revision Changed Before Installation')
  const beforeReceipt=fs.existsSync(path.join(bundle,'receipt.json'))
  const applied=invoke(setupDir,mode,root,bundle)
  if(!applied.ok){
   let rollback=null
   // Only this invocation's newly prepared receipt can authorize automatic rollback.
   if(mode==='apply' && !beforeReceipt && fs.existsSync(path.join(bundle,'receipt.json'))){
    const receipt=readJson(contained(bundle,'receipt.json'))
    if(receipt.state==='prepared' && receipt.releaseSha===entry.releaseSha256)rollback=invoke(setupDir,'rollback',root,bundle)
   }
   const error=Error(applied.error);error.installationFailed=true;error.rollback=rollback;throw error
  }
  const validation=invoke(setupDir,'check',root,bundle)
  assert(validation.ok,'Installation Readback Failed')
  const expected=mode==='rollback'?'ready':applied.result.state==='ready'?'ready':'already_installed'
  assert.equal(validation.result.state,expected,'Installation Readback State Differs')
  return {...applied.result,operation:mode,desktopHead:head,validation:validation.result,windowReloaded:false}
 }finally{release()}
}
if(process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
 try{
  assert.equal(process.argv.length,3,'One Fixed Operation Is Required')
  console.log(JSON.stringify(runSetup({mode:process.argv[2]})))
 }catch(error){
  console.log(JSON.stringify({state:error.installationFailed?'failed':'blocked',verified:false,reason:error.message,rollback:error.rollback??null,windowReloaded:false}))
  process.exitCode=error.installationFailed?1:2
 }
}
