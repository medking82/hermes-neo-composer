// Real Windows filesystem rehearsal; all writes stay below this release's test area.
import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { execFileSync, spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const base=path.dirname(fileURLToPath(import.meta.url)),live=process.argv[2]
assert(live)
const label=process.argv[3]||'installer-rehearsal-final'
assert(/^[a-z0-9-]+$/.test(label))
const area=path.join(base,label),root=path.join(area,'root'),bundle=path.join(area,'bundle'),home=path.join(area,'home')
assert(!fs.existsSync(area),'Rehearsal already exists; inspect rather than overwrite evidence')
fs.mkdirSync(area)
execFileSync('git',['-C',live,'worktree','add','--detach',root,'d923a5eb487a17c0a68801bba9ef0f56c81040a8'])
fs.mkdirSync(bundle)
const copy=(from,to)=>{fs.mkdirSync(path.dirname(to),{recursive:true});fs.cpSync(from,to,{recursive:true,errorOnExist:true,force:false})}
for(const f of ['install.mjs','prepare.mjs','compat.mjs','backend.mjs','release-seed.json','build-receipt.json'])copy(path.join(base,f),path.join(bundle,f))
copy(path.join(base,'dist'),path.join(bundle,'dist'))
copy(path.join(base,'candidate-renderer'),path.join(bundle,'candidate-renderer'))
const seed=JSON.parse(fs.readFileSync(path.join(base,'release-seed.json'),'utf8'))
// Approval-like data apply ONLY to this copied test target, never to the live seed.
const fixture=JSON.parse(fs.readFileSync(path.join(base,'runtime-fixture.json'),'utf8'))
assert.equal(fixture.scope,'isolated-rehearsal-only')
seed.runtime=fixture.runtime
fs.writeFileSync(path.join(bundle,'release-seed.json'),JSON.stringify(seed,null,2))
for(const entry of seed.sources){
 const source=path.join(live,entry.path),dest=path.join(root,entry.path)
 if(entry.before===null){assert(!fs.existsSync(source),'Unexpected live source: '+entry.path);continue}
 assert.equal(createHash('sha256').update(fs.readFileSync(source)).digest('hex'),entry.before,'Predecessor drift: '+entry.path)
 fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(source,dest)
}
for(const e of seed.sources)copy(path.join(base,'checkout',e.path),path.join(bundle,'checkout',e.path))
for(const f of ['composer-smoke.tsx','composer-smoke.html','composer-smoke.vite.ts','composer-controller.mjs','composer-settings.mjs'])copy(path.join(base,'checkout/apps/desktop',f),path.join(bundle,'checkout/apps/desktop',f))
const rel='apps/desktop/release/win-unpacked'
for(const f of ['Hermes.exe','resources/app.asar','resources/install-stamp.json','resources/app.asar.unpacked/dist'])copy(path.join(live,rel,f),path.join(root,rel,f))
const previous=path.join(base,'previous-plugin'),plugin=path.join(home,'desktop-plugins/neo-next-prompt')
for(const entry of seed.pluginFiles){
 assert.equal(createHash('sha256').update(fs.readFileSync(path.join(previous,entry.path))).digest('hex'),entry.before)
 copy(path.join(previous,entry.path),path.join(plugin,entry.path))
}
const env={...process.env,HERMES_HOME:home}
const run=(file,args=[])=>{const r=spawnSync(process.execPath,[path.join(bundle,file),...args],{encoding:'utf8',env});return {code:r.status,stdout:r.stdout,stderr:r.stderr}}
const good=(file,args=[])=>{const r=run(file,args);assert.equal(r.code,0,r.stderr+r.stdout);return JSON.parse(r.stdout.trim())}
const prepared=good('prepare.mjs',[root,bundle])
const release=JSON.parse(fs.readFileSync(path.join(bundle,'release.json'),'utf8'))
const rendererRoot=path.join(root,rel,'resources/app.asar.unpacked/dist')
const introduced=Object.keys(release.renderer).filter(name=>!fs.existsSync(path.join(rendererRoot,name)))
assert(introduced.length>0,'The real rehearsal must exercise new renderer assets')
assert.equal(prepared.pluginDir,path.join(home,'desktop-plugins/neo-next-prompt'))
const ready=good('install.mjs',['check',root,bundle])
assert.equal(ready.state,'ready')
const protectedFile=path.join(root,rel,'resources/app.asar'),protectedBytes=fs.readFileSync(protectedFile)
try{
 fs.appendFileSync(protectedFile,'runtime drift fixture')
 const refused=run('install.mjs',['check',root,bundle])
 assert.notEqual(refused.code,0,'Runtime drift was accepted')
 assert.match(refused.stderr,/Packaged Electron runtime drift/)
}finally{fs.writeFileSync(protectedFile,protectedBytes)}
const apply=good('install.mjs',['apply',root,bundle])
assert.equal(apply.state,'installed')
const appliedReceipt=JSON.parse(fs.readFileSync(path.join(bundle,'receipt.json'),'utf8'))
assert.deepEqual(Object.keys(appliedReceipt.protected).sort(),Object.keys(fixture.runtime.pins).map(f=>path.join(root,f)).sort(),'Every native fingerprint file must stay protected after apply and during rollback')
assert.equal(good('install.mjs',['apply',root,bundle]).state,'already_installed')
assert.equal(good('install.mjs',['check-update',root,bundle]).compatible,true)
const file=path.join(root,'apps/desktop/src/sdk/composer.ts'),original=fs.readFileSync(file)
fs.appendFileSync(file,'\n// foreign edit fixture\n')
assert.notEqual(run('install.mjs',['check',root,bundle]).code,0)
assert.notEqual(run('install.mjs',['rollback',root,bundle]).code,0)
assert(fs.readFileSync(file,'utf8').endsWith('// foreign edit fixture\n'),'foreign edit overwritten')
fs.writeFileSync(file,original)
const rolled=good('install.mjs',['rollback',root,bundle])
assert.equal(rolled.state,'rolled_back')
assert.deepEqual(introduced.filter(name=>fs.existsSync(path.join(rendererRoot,name))),[],'Uninstall left owned renderer assets behind')
assert.equal(good('install.mjs',['rollback',root,bundle]).state,'rolled_back')
const hash=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex')
for(const f of Object.keys(fixture.runtime.pins)){
 const a=path.join(live,f),b=path.join(root,f)
 assert.equal(hash(a),hash(b),f)
}
const result={status:'passed',scope:'isolated Windows worktree; no live install',area,prepare:prepared.state,apply:apply.state,secondApply:'already_installed',foreignEditCheckRejected:true,foreignEditRollbackRejected:true,rollback:rolled.state,secondRollback:'rolled_back',protectedRuntimeUnchanged:true,introducedRendererAssetsRemoved:introduced.length}
fs.writeFileSync(path.join(area,'result.json'),JSON.stringify(result,null,2))
console.log(JSON.stringify(result))
