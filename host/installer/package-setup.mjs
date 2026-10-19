// Maintainer-only assembly from an already prepared, frozen release. No live writes.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { ordinary, atomic } from './backend.mjs'
import { assertPluginPolicy } from './compat.mjs'
const here=path.dirname(fileURLToPath(import.meta.url))
const digest=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex')
export function assembleSetupPackage({destination,desktopRoot,packages}){
 assert(typeof destination==='string' && path.isAbsolute(destination),'Absolute Destination Required')
 assert(!fs.existsSync(destination),'Destination Already Exists; Never Overwrite A Package Or Its Backups')
 assert(typeof desktopRoot==='string' && path.isAbsolute(desktopRoot),'Absolute Desktop Root Required')
 assert(Array.isArray(packages) && packages.length>0,'At Least One Frozen Package Is Required')
 const ids=new Set(),heads=new Set(),inputs=[]
 for(const item of packages){
  assert(typeof item.id==='string' && /^[a-z0-9][a-z0-9-]{0,79}$/.test(item.id) && !ids.has(item.id),'Invalid Or Duplicate Package Id');ids.add(item.id)
  const release=ordinary(item.bundle,'release.json'),manifest=JSON.parse(fs.readFileSync(release,'utf8'))
  assertPluginPolicy(manifest)
  assert(!fs.existsSync(path.join(item.bundle,'receipt.json')) && !fs.existsSync(path.join(item.bundle,'backup')),'Package Already Used; Keep Its Receipt And Backups In Place')
  assert(Array.isArray(manifest.roles?.desktop?.heads) && manifest.roles.desktop.heads.length>0,'Missing Desktop Revisions')
  for(const head of manifest.roles.desktop.heads){assert(typeof head==='string' && /^[a-f0-9]{40}$/.test(head) && !heads.has(head),'Invalid Or Ambiguous Desktop Revision');heads.add(head)}
  const buildReceiptSha=digest(ordinary(item.bundle,'build-receipt.json'))
  assert.equal(buildReceiptSha,manifest.buildReceiptSha,'Build Receipt Changed')
  const files={'release.json':digest(release),'build-receipt.json':buildReceiptSha}
  for(const entry of manifest.sources)if(entry.after!==null)files['source/'+entry.path]=entry.after
  for(const entry of manifest.pluginFiles)files['dist/'+entry.path]=entry.after
  for(const [name,hash] of Object.entries(manifest.renderer))files['candidate-renderer/'+name]=hash
  for(const [name,hash] of Object.entries(files)){assert(typeof hash==='string' && /^[a-f0-9]{64}$/.test(hash),'Invalid Payload Digest');assert.equal(digest(ordinary(item.bundle,name)),hash,'Frozen Payload Changed: '+name)}
  inputs.push({item,manifest,files})
 }
 fs.mkdirSync(destination)
 const tools={}
 for(const name of ['install.mjs','compat.mjs','backend.mjs','setup.mjs','NeoComposerSetup.cmd','NeoComposerCheck.cmd','NeoComposerUninstall.cmd']){
  const source=ordinary(here,name);atomic(source,ordinary(destination,name))
  if(name.endsWith('.mjs'))tools[name]=digest(source)
 }
 const catalog={schema:1,desktopRoot,tools,packages:[]}
 for(const {item,manifest,files} of inputs){
  const directory='packages/'+item.id
  for(const [name,hash] of Object.entries(files)){
   const target=ordinary(destination,directory+'/'+name);fs.mkdirSync(path.dirname(target),{recursive:true});atomic(ordinary(item.bundle,name),target);assert.equal(digest(target),hash,'Assembled Payload Differs')
  }
  catalog.packages.push({id:item.id,directory,heads:manifest.roles.desktop.heads,releaseSha256:files['release.json']})
 }
 fs.writeFileSync(path.join(destination,'catalog.json'),JSON.stringify(catalog,null,2)+'\n',{flag:'wx'})
 return {state:'assembled',packages:inputs.length,destination,installed:false}
}
if(process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
 try{assert.equal(process.argv.length,6,'Use DESTINATION DESKTOP_ROOT PACKAGE_ID FROZEN_BUNDLE');const [destination,desktopRoot,id,bundle]=process.argv.slice(2);console.log(JSON.stringify(assembleSetupPackage({destination,desktopRoot,packages:[{id,bundle}]})))}
 catch(error){console.error(error.message);process.exitCode=2}
}
