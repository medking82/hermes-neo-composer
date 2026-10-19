import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { spawnSync, execFileSync } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { desktopFixture } from './desktop-fixture.mjs'
import { runSetup } from './setup.mjs'
const sha=data=>createHash('sha256').update(data).digest('hex')
const here=path.dirname(fileURLToPath(import.meta.url))
function fixture(t){
 const f=desktopFixture(t), setupDir=path.join(f.area,'setup'), lockDir=path.join(f.area,'locks'), packageDir=path.join(setupDir,'packages','fixture')
 fs.mkdirSync(path.dirname(packageDir),{recursive:true});fs.renameSync(f.bundle,packageDir)
 const tools={}
 for(const name of ['install.mjs','compat.mjs','backend.mjs','setup.mjs']){const bytes=fs.readFileSync(path.join(here,name));fs.writeFileSync(path.join(setupDir,name),bytes);tools[name]=sha(bytes)}
 const bytes=fs.readFileSync(path.join(packageDir,'release.json')),head=JSON.parse(bytes).roles.desktop.heads[0]
 const catalog={schema:1,desktopRoot:f.root,tools,packages:[{id:'fixture',heads:[head],directory:'packages/fixture',releaseSha256:sha(bytes)}]}
 const save=()=>fs.writeFileSync(path.join(setupDir,'catalog.json'),JSON.stringify(catalog))
 save()
 return {...f,setupDir,lockDir,packageDir,catalog,save,run:mode=>runSetup({setupDir,lockDir,mode})}
}
test('standalone setup selects a known package and reuses check, apply, idempotence and rollback',t=>{
 const f=fixture(t)
 assert.equal(f.run('check').state,'ready')
 const applied=f.run('apply');assert.equal(applied.state,'installed');assert.equal(applied.validation.state,'already_installed')
 assert.equal(fs.readFileSync(path.join(f.root,f.source),'utf8'),'after source')
 assert.equal(f.run('apply').state,'already_installed')
 assert.equal(f.run('rollback').state,'rolled_back')
 assert.equal(fs.readFileSync(path.join(f.root,f.source),'utf8'),'before source')
 assert.equal(fs.readdirSync(f.lockDir).length,0)
})
test('unknown host revisions and ambiguous matching packages refuse before writes',t=>{
 const f=fixture(t);f.catalog.packages[0].heads=['a'.repeat(40)];f.save()
 assert.throws(()=>f.run('apply'),/Unsupported Host Version/)
 assert.equal(fs.existsSync(path.join(f.packageDir,'receipt.json')),false)
 f.catalog.packages[0].heads=JSON.parse(fs.readFileSync(path.join(f.packageDir,'release.json'))).roles.desktop.heads
 f.catalog.packages.push({...f.catalog.packages[0],id:'duplicate',directory:'packages/duplicate'});f.save()
 assert.throws(()=>f.run('apply'),/Ambiguous Enhancement Packages/)
 assert.equal(fs.readFileSync(path.join(f.root,f.source),'utf8'),'before source')
})
test('changed release manifests and installer tools cannot execute',t=>{
 const f=fixture(t)
 fs.appendFileSync(path.join(f.packageDir,'release.json'),' ')
 assert.throws(()=>f.run('apply'),/Release Integrity Mismatch/)
 f.catalog.packages[0].releaseSha256=sha(fs.readFileSync(path.join(f.packageDir,'release.json')));f.save()
 fs.appendFileSync(path.join(f.setupDir,'install.mjs'),'\n// fixture drift')
 assert.throws(()=>f.run('apply'),/Tool Integrity Mismatch/)
 assert.equal(fs.readFileSync(path.join(f.root,f.source),'utf8'),'before source')
})
test('catalog paths and malformed revision identifiers are rejected rather than repaired',t=>{
 const f=fixture(t)
 for(const directory of ['../fixture','/absolute','packages/../fixture','packages\\..\\fixture','packages/fixture:stream']){
  f.catalog.packages[0].directory=directory;f.save();assert.throws(()=>f.run('check'),/Unsafe Package Directory/)
 }
 f.catalog.packages[0].directory='packages/fixture';f.catalog.packages[0].heads=['A'.repeat(40)];f.save()
 assert.throws(()=>f.run('check'),/Invalid Desktop Revision/)
})
test('the actual CLI refuses force options and returns a structured nonzero receipt',t=>{
 const f=fixture(t),result=spawnSync(process.execPath,[path.join(f.setupDir,'setup.mjs'),'--force'],{encoding:'utf8'})
 assert.equal(result.status,2,result.stderr)
 assert.equal(JSON.parse(result.stdout).state,'blocked')
 assert.equal(fs.readFileSync(path.join(f.root,f.source),'utf8'),'before source')
})
test('a new partial apply rolls back only its own verified prepared receipt',t=>{
 const f=fixture(t),fault=path.join(f.area,'fault.mjs')
 fs.writeFileSync(fault,`import fs from 'node:fs';const copy=fs.copyFileSync;fs.copyFileSync=(a,b,...rest)=>{if(process.argv.includes('apply')&&b===${JSON.stringify(path.join(f.root,f.source)+'.neo-new')})throw Error('fixture-copy-failure');return copy(a,b,...rest)}`)
 const result=spawnSync(process.execPath,[path.join(f.setupDir,'setup.mjs'),'apply'],{encoding:'utf8',env:{...process.env,NODE_OPTIONS:'--import='+pathToFileURL(fault).href}})
 assert.equal(result.status,1,result.stderr)
 const receipt=JSON.parse(result.stdout)
 assert.equal(receipt.state,'failed');assert.equal(receipt.verified,false)
 assert.equal(receipt.rollback.result.state,'rolled_back')
 assert.equal(fs.readFileSync(path.join(f.root,f.source),'utf8'),'before source')
 assert.equal(fs.existsSync(path.join(f.root,f.renderer,'assets/owned.js')),false)
})
test('unknown revisions cannot restore an old backup; a matching revision can',t=>{
 const f=fixture(t);f.run('apply')
 execFileSync('git',['-C',f.root,'commit','--allow-empty','-qm','synthetic revision change'])
 assert.throws(()=>f.run('rollback'),/Unsupported Host Version/)
 assert.equal(fs.readFileSync(path.join(f.root,f.source),'utf8'),'after source')
 execFileSync('git',['-C',f.root,'reset','--soft',f.catalog.packages[0].heads[0]])
 assert.equal(f.run('rollback').state,'rolled_back')
})
test('an existing target lock is preserved and prevents another installation',t=>{
 const f=fixture(t);fs.mkdirSync(f.lockDir)
 const key=sha(process.platform==='win32'?fs.realpathSync(f.root).toLowerCase():fs.realpathSync(f.root)),lock=path.join(f.lockDir,key+'.lock')
 fs.writeFileSync(lock,'fixture-existing-lock')
 assert.throws(()=>f.run('apply'),/Installer Already Running/)
 assert.equal(fs.readFileSync(lock,'utf8'),'fixture-existing-lock')
 assert.equal(fs.readFileSync(path.join(f.root,f.source),'utf8'),'before source')
})
test('Windows launcher actions are fixed and never forward arbitrary arguments',()=>{
 for(const [name,mode] of [['NeoComposerSetup.cmd','apply'],['NeoComposerCheck.cmd','check'],['NeoComposerUninstall.cmd','rollback']]){
  const source=fs.readFileSync(path.join(here,name),'utf8')
  assert.ok(source.includes('node "%~dp0setup.mjs" '+mode))
  assert.ok(!source.includes('%*'))
  assert.ok(source.includes('exit /b %code%'))
 }
})
