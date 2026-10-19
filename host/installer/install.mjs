// Fixed-release installer. No service restart, updater, polling or force mode.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { assertCompatible, runtimeFingerprint, assertPluginBaseline, assertPluginPolicy, isComposerSource } from './compat.mjs'
import { backendTransition, ordinary, atomic as copyAtomic } from './backend.mjs'

const args = process.argv.slice(2)
assert.equal(args.length, 3, 'Use MODE ROOT BUNDLE; no --force option')
const [mode, rootArg, bundleArg] = args
assert(['check','apply','rollback','check-update','check-backend-update','check-backend','apply-backend','rollback-backend'].includes(mode), 'Unknown mode')
const root = path.resolve(rootArg), bundle = path.resolve(bundleArg)
const manifestPath = path.join(bundle, 'release.json')
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
const digest = file => fs.existsSync(file) ? createHash('sha256').update(fs.readFileSync(file)).digest('hex') : null
const releaseSha = digest(manifestPath)
const safe = name => { assert(!path.isAbsolute(name) && !name.split(/[\\/]/).includes('..'), 'Unsafe release path'); return name }
const head = execFileSync('git', ['-C',root,'rev-parse','HEAD'], {encoding:'utf8'}).trim()
if (['check-backend','apply-backend','rollback-backend'].includes(mode)) {
  console.log(JSON.stringify(backendTransition(mode, root, bundle, manifest, releaseSha, head)))
  process.exit(0)
}
if (mode === 'check-update' || mode === 'check-backend-update') {
  const role = mode === 'check-update' ? 'desktop' : 'backend'
  const actual = Object.fromEntries(Object.keys(manifest.roles[role].pins).map(file => [file,digest(path.join(root,safe(file)))]))
  console.log(JSON.stringify(assertCompatible(role, head, actual, manifest)))
  process.exit(0)
}
const preservePlugin = assertPluginPolicy(manifest) === 'preserve'
assert(manifest.roles.desktop.heads.includes(head), `Unsupported host version ${head}; stop`)
assert.deepEqual(runtimeFingerprint(root,manifest.roles.desktop.heads,manifest.runtime),manifest.runtime,'Packaged Electron runtime drift; refuse renderer replacement')
const dirty = execFileSync('git',['-C',root,'status','--porcelain','--untracked-files=all'],{encoding:'utf8'}).split(/\r?\n/).filter(Boolean).map(line=>line.slice(3).replaceAll('\\','/'))
const allowed = new Set(manifest.sources.map(entry=>entry.path))
for (const name of dirty) assert(allowed.has(name), `Unknown checkout edit: ${name}`)
for (const entry of manifest.sources) { safe(entry.path); assert(isComposerSource(entry.path)) }
// Imports from the target happen only after its version and dirty tree guards.
const { resolveDesktopHermesHome } = await import(pathToFileURL(path.join(root,'apps/desktop/electron/data-paths.mjs')).href)
const home = resolveDesktopHermesHome({home:os.homedir(),directoryExists:fs.existsSync,readWindowsHome:()=>process.platform==='win32' ? execFileSync('powershell',['-NoProfile','-Command',"[Console]::Write([Environment]::GetEnvironmentVariable('HERMES_HOME','User'))"],{encoding:'utf8'}).trim() : null})
assert.equal(path.resolve(manifest.pluginRoot), path.resolve(home,'desktop-plugins'), 'Desktop home changed; refuse wrong plugin root')
const pluginDir = path.join(manifest.pluginRoot,'neo-next-prompt')
const target = path.join(root,'apps/desktop/release/win-unpacked/resources/app.asar.unpacked/dist')
const candidate = path.join(bundle,'candidate-renderer')
const backup = path.join(bundle,'backup')
const receiptFile = path.join(bundle,'receipt.json')
const controls = ['renderer-manifest.json','index.html']
const introducedRenderer = manifest.introducedRenderer
assert(Array.isArray(introducedRenderer), 'Missing renderer ownership inventory; prepare a new release')
assert.equal(new Set(introducedRenderer).size, introducedRenderer.length, 'Duplicate renderer ownership')
for(const name of introducedRenderer){safe(name);assert(!controls.includes(name)&&manifest.renderer[name], 'Invalid renderer ownership')}
// Inspect parents too: a matching file hash does not make a junction ours.
for(const name of Object.keys(manifest.renderer))ordinary(root,'apps/desktop/release/win-unpacked/resources/app.asar.unpacked/dist/'+safe(name))
for(const entry of manifest.sources)ordinary(root,entry.path)
for(const entry of manifest.pluginFiles)ordinary(home,'desktop-plugins/neo-next-prompt/'+safe(entry.path))
ordinary(bundle,'receipt.json');ordinary(bundle,'receipt.json.new')
const protectedPaths = Object.keys(manifest.runtime.pins).map(name=>path.join(root,safe(name)))
const protectedNow = ()=>Object.fromEntries(protectedPaths.map(file=>[file,digest(file)]))
const sourceState = ()=>Object.fromEntries(manifest.sources.map(entry=>[entry.path,digest(path.join(root,entry.path))]))
const controlState = ()=>Object.fromEntries(controls.map(name=>[name,digest(path.join(target,name))]))
const pluginState = ()=>Object.fromEntries(manifest.pluginFiles.map(entry=>[entry.path,digest(path.join(pluginDir,safe(entry.path)))]))
const state = ()=>({sources:sourceState(),controls:controlState(),plugin:pluginState()})
const before = {sources:Object.fromEntries(manifest.sources.map(entry=>[entry.path,entry.before])),controls:manifest.beforeControls,plugin:Object.fromEntries(manifest.pluginFiles.map(entry=>[entry.path,entry.before]))}
const after = {sources:Object.fromEntries(manifest.sources.map(entry=>[entry.path,entry.after])),controls:Object.fromEntries(controls.map(name=>[name,manifest.renderer[name]])),plugin:Object.fromEntries(manifest.pluginFiles.map(entry=>[entry.path,entry.after]))}
const same = (a,b)=>{try{assert.deepEqual(a,b);return true}catch{return false}}
const atomic = (from,to)=>{fs.mkdirSync(path.dirname(to),{recursive:true});copyAtomic(from,to)}
const save = record=>{const temp=receiptFile+'.new';fs.writeFileSync(temp,JSON.stringify(record,null,2));fs.renameSync(temp,receiptFile)}
const putOrRemove = (source,dest,sha)=>{if(sha===null){if(fs.existsSync(dest))fs.unlinkSync(dest)}else atomic(source,dest)}
const { missingRendererAssets } = await import(pathToFileURL(path.join(root,'apps/desktop/electron/renderer-bundle.ts')).href)

if(mode==='rollback') {
  const receipt=JSON.parse(fs.readFileSync(receiptFile,'utf8'))
  assert.equal(receipt.releaseSha,releaseSha,'Receipt belongs to a different release')
  assert.deepEqual(protectedNow(),receipt.protected,'Electron/runtime drift')
  const current=state()
  for(const group of ['sources','controls','plugin'])for(const [name,sha] of Object.entries(current[group]))assert(sha===before[group][name]||sha===after[group][name],`Unknown ${group} edit: ${name}`)
  // Verify every backup BEFORE restoring any entry, source or plugin.
  for(const entry of manifest.sources)if(entry.before!==null)assert.equal(digest(ordinary(bundle,'backup/source/'+entry.path)),entry.before)
  for(const name of controls)assert.equal(digest(ordinary(bundle,'backup/renderer/'+name)),before.controls[name])
  for(const entry of manifest.pluginFiles)if(entry.before!==null)assert.equal(digest(ordinary(bundle,'backup/plugin/'+entry.path)),entry.before)
  for(const name of introducedRenderer){const sha=digest(path.join(target,name));assert(sha===null||sha===manifest.renderer[name],`Unknown renderer edit: ${name}`)}
  for(const name of controls)atomic(path.join(backup,'renderer',name),path.join(target,name))
  for(const entry of manifest.sources)putOrRemove(path.join(backup,'source',entry.path),path.join(root,entry.path),entry.before)
  for(const entry of manifest.pluginFiles)putOrRemove(path.join(backup,'plugin',entry.path),path.join(pluginDir,entry.path),entry.before)
  for(const name of introducedRenderer){const file=path.join(target,name);if(fs.existsSync(file))fs.unlinkSync(file)}
  assert.deepEqual(state(),before)
  assert.deepEqual(missingRendererAssets(path.join(target,'index.html')),[])
  assert.deepEqual(protectedNow(),receipt.protected)
  save({...receipt,state:'rolled_back'})
  console.log(JSON.stringify({state:'rolled_back',verified:true,windowReloaded:false,pluginPreserved:preservePlugin,decisionsPreserved:true}))
} else if(same(state(),after)) {
  for(const [name,sha] of Object.entries(manifest.renderer))assert.equal(digest(path.join(target,name)),sha,`Installed renderer drift: ${name}`)
  const receipt=JSON.parse(fs.readFileSync(receiptFile,'utf8'))
  assert.equal(receipt.releaseSha,releaseSha)
  assert.deepEqual(protectedNow(),receipt.protected)
  assert.deepEqual(missingRendererAssets(path.join(target,'index.html')),[])
  console.log(JSON.stringify({state:'already_installed',verified:true,windowReloaded:false,pluginPreserved:preservePlugin}))
} else {
  assert.deepEqual(state(),before,'Unknown source/renderer/plugin edits; refuse overwrite')
  for(const name of introducedRenderer)assert(!fs.existsSync(path.join(target,name)),`Renderer ownership changed since preparation: ${name}`)
  if(!preservePlugin)assertPluginBaseline(pluginDir,manifest.pluginFiles)
  assert.deepEqual(missingRendererAssets(path.join(candidate,'index.html')),[])
  for(const entry of manifest.sources)assert.equal(digest(path.join(bundle,'source',entry.path)),entry.after,`Source payload drift: ${entry.path}`)
  for(const entry of manifest.pluginFiles)assert.equal(digest(path.join(bundle,'dist',safe(entry.path))),entry.after,`Plugin payload drift: ${entry.path}`)
  for(const [name,sha] of Object.entries(manifest.renderer)) {
    safe(name);assert(!name.startsWith('electron-'),'No Electron payload allowed')
    assert.equal(digest(path.join(candidate,name)),sha,`Renderer payload drift: ${name}`)
    if(!controls.includes(name)&&fs.existsSync(path.join(target,name)))assert.equal(digest(path.join(target,name)),sha,`Asset collision: ${name}`)
  }
  if(mode==='check')console.log(JSON.stringify({state:'ready',verified:true,pluginRoot:manifest.pluginRoot,protocol:1}))
  else {
    assert(!fs.existsSync(backup),'Existing backup; inspect before a new explicit release')
    const protectedBefore=protectedNow()
    for(const entry of manifest.sources)if(entry.before!==null){const dest=path.join(backup,'source',entry.path);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(path.join(root,entry.path),dest,fs.constants.COPYFILE_EXCL)}
    for(const name of controls){const dest=path.join(backup,'renderer',name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(path.join(target,name),dest,fs.constants.COPYFILE_EXCL)}
    for(const entry of manifest.pluginFiles)if(entry.before!==null){const dest=path.join(backup,'plugin',entry.path);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(path.join(pluginDir,entry.path),dest,fs.constants.COPYFILE_EXCL)}
    save({state:'prepared',releaseSha,protected:protectedBefore})
    for(const [name] of Object.entries(manifest.renderer))if(!controls.includes(name)&&!fs.existsSync(path.join(target,name))){const dest=path.join(target,name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(path.join(candidate,name),dest,fs.constants.COPYFILE_EXCL)}
    for(const entry of manifest.sources)putOrRemove(path.join(bundle,'source',entry.path),path.join(root,entry.path),entry.after)
    for(const name of controls)atomic(path.join(candidate,name),path.join(target,name))
    // The independently saved disk plugin is published last; no core editing code lives in it.
    for(const entry of manifest.pluginFiles)atomic(path.join(bundle,'dist',entry.path),path.join(pluginDir,entry.path))
    assert.deepEqual(state(),after)
    assert.deepEqual(missingRendererAssets(path.join(target,'index.html')),[])
    assert.deepEqual(protectedNow(),protectedBefore)
    save({state:'installed',releaseSha,protected:protectedBefore,pluginDir,verified:true})
    console.log(JSON.stringify({state:'installed',verified:true,pluginDir,protectedUnchanged:true,windowReloaded:false,pluginPreserved:preservePlugin}))
  }
}
