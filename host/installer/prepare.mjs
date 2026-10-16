// Prepare a pinned release only; never changes a live source or plugin file.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'
import { runtimeFingerprint, assertPluginBaseline, isComposerSource } from './compat.mjs'
const [rootArg,bundleArg]=process.argv.slice(2)
assert(rootArg&&bundleArg)
const root=path.resolve(rootArg),bundle=path.resolve(bundleArg)
const output=path.join(bundle,'release.json')
assert(!fs.existsSync(output),'Release already frozen; use check instead of regenerating')
const seed=JSON.parse(fs.readFileSync(path.join(bundle,'release-seed.json'),'utf8'))
const hash=f=>fs.existsSync(f)?createHash('sha256').update(fs.readFileSync(f)).digest('hex'):null
const safe=f=>{assert(!path.isAbsolute(f)&&!f.split(/[\\/]/).includes('..'));return f}
const head=execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim()
assert(seed.roles.desktop.heads.includes(head),'Unknown target version')
const allowed=new Set(seed.sources.map(e=>e.path))
const dirty=execFileSync('git',['-C',root,'status','--porcelain','--untracked-files=all'],{encoding:'utf8'}).split(/\r?\n/).filter(Boolean).map(l=>l.slice(3).replaceAll('\\','/'))
for(const f of dirty)assert(allowed.has(f),`Unknown source edit: ${f}`)
for(const e of seed.sources){safe(e.path);assert(isComposerSource(e.path));assert.equal(hash(path.join(root,e.path)),e.before,`Live source changed: ${e.path}`);assert.equal(hash(path.join(bundle,'checkout',e.path)),e.after,`Build source changed: ${e.path}`)}
const {resolveDesktopHermesHome}=await import(pathToFileURL(path.join(root,'apps/desktop/electron/data-paths.mjs')).href)
const home=resolveDesktopHermesHome({home:os.homedir(),directoryExists:fs.existsSync,readWindowsHome:()=>process.platform==='win32'?execFileSync('powershell',['-NoProfile','-Command',"[Console]::Write([Environment]::GetEnvironmentVariable('HERMES_HOME','User'))"],{encoding:'utf8'}).trim():null})
const pluginRoot=path.join(home,'desktop-plugins'),pluginDir=path.join(pluginRoot,'neo-next-prompt')
assertPluginBaseline(pluginDir,seed.pluginFiles)
for(const e of seed.pluginFiles){safe(e.path);assert.equal(hash(path.join(bundle,'dist',e.path)),e.after)}
for(const e of seed.sources)if(e.after!==null){const dest=path.join(bundle,'source',e.path);fs.mkdirSync(path.dirname(dest),{recursive:true});if(fs.existsSync(dest))assert.equal(hash(dest),e.after);else fs.copyFileSync(path.join(bundle,'checkout',e.path),dest,fs.constants.COPYFILE_EXCL)}
const renderer={}
function collect(dir,prefix=''){
 for(const e of fs.readdirSync(dir,{withFileTypes:true})){
  const relative=prefix+e.name,full=path.join(dir,e.name)
  assert(!e.isSymbolicLink(),'No symlink payloads')
  if(e.isDirectory())collect(full,relative+'/');else if(e.isFile())renderer[relative]=hash(full)
 }
}
collect(path.join(bundle,'candidate-renderer'))
const built=JSON.parse(fs.readFileSync(path.join(bundle,'build-receipt.json'),'utf8'))
assert.equal(built.head,head,'Renderer built from a different HEAD')
assert.deepEqual(built.sourcePins,Object.fromEntries(seed.sources.map(e=>[e.path,e.after])),'Renderer source provenance differs')
assert.deepEqual(built.renderer,renderer,'Renderer changed since its sealed build')
for(const [name,sha] of Object.entries(built.dirty)){safe(name);assert.equal(hash(path.join(bundle,'checkout',name)),sha,'Build input changed: '+name)}
const live=path.join(root,'apps/desktop/release/win-unpacked/resources/app.asar.unpacked/dist')
const introducedRenderer=Object.keys(renderer).filter(name=>!fs.existsSync(path.join(live,safe(name))))
const beforeControls=Object.fromEntries(['renderer-manifest.json','index.html'].map(f=>[f,hash(path.join(live,f))]))
assert(Object.values(beforeControls).every(Boolean))
const runtime=runtimeFingerprint(root,seed.roles.desktop.heads,seed.runtime)
const manifest={...seed,pluginRoot,beforeControls,renderer,introducedRenderer,runtime,buildReceiptSha:hash(path.join(bundle,'build-receipt.json'))}
fs.writeFileSync(output,JSON.stringify(manifest,null,2),{flag:'wx'})
console.log(JSON.stringify({state:'prepared',sourceEntries:seed.sources.length,rendererFiles:Object.keys(renderer).length,pluginDir}))
