import test from 'node:test'
import assert from 'node:assert/strict'
import { validInstallerPath, chooseEnhancementInstaller, launchEnhancementInstaller } from './enhancement.mjs'
const installer='C:\\Users\\Fixture\\Neo Composer\\NeoComposerSetup.cmd'
const fixture=()=>{
 const values=new Map(),opened=[]
 const ctx={storage:{get:(k,f)=>values.get(k)??f,set:(k,v)=>values.set(k,v)},os:{pickOpenPath:async()=>installer,openExternal:async path=>{opened.push(path);return true}}}
 return {ctx,values,opened}
}

test('installer selection persists one explicit local launcher without executing it',async()=>{
 const f=fixture();assert.equal(validInstallerPath(installer),true)
 assert.deepEqual(await chooseEnhancementInstaller(f.ctx),{ok:true,path:installer})
 assert.deepEqual(f.opened,[])
 assert.equal(f.values.get('enhancement.installerPath'),installer)
})
test('a separate user launch sends only the chosen path, not a shell command or backend request',async()=>{
 const f=fixture();await chooseEnhancementInstaller(f.ctx)
 const result=await launchEnhancementInstaller(f.ctx)
 assert.deepEqual(f.opened,[installer])
 assert.deepEqual(result,{ok:true,state:'requested',installed:false})
 assert.equal(f.ctx.rest,undefined)
})
test('cancel or unavailable picker does not remove a saved installer',async()=>{
 const f=fixture();await chooseEnhancementInstaller(f.ctx);f.ctx.os.pickOpenPath=async()=>null
 assert.equal((await chooseEnhancementInstaller(f.ctx)).ok,false)
 assert.equal(f.values.get('enhancement.installerPath'),installer)
 delete f.ctx.os.pickOpenPath
 assert.equal((await chooseEnhancementInstaller(f.ctx)).ok,false)
})
test('installer paths reject URLs, traversal, device/UNC paths, ADS and command arguments',async()=>{
 for(const path of ['',null,42,'https://example.com/NeoComposerSetup.cmd','file:///C:/NeoComposerSetup.cmd','\\\\server\\share\\NeoComposerSetup.cmd','\\\\?\\C:\\NeoComposerSetup.cmd','C:\\..\\NeoComposerSetup.cmd','C:\\x:stream\\NeoComposerSetup.cmd','C:\\other.cmd','C:\\NeoComposerSetup.cmd --force','C:\\NeoComposerSetup.cmd\n','C:\\NeoComposerSetup.cmd" & anything']){
  assert.equal(validInstallerPath(path),false,String(path))
  const f=fixture();f.values.set('enhancement.installerPath',path)
  assert.equal((await launchEnhancementInstaller(f.ctx)).ok,false,String(path))
  assert.deepEqual(f.opened,[])
 }
})
test('a failed open is not reported as installation or a successful launch',async()=>{
 const f=fixture();await chooseEnhancementInstaller(f.ctx)
 f.ctx.os.openExternal=async()=>false
 assert.equal((await launchEnhancementInstaller(f.ctx)).ok,false)
 f.ctx.os.openExternal=async()=>{throw Error('fixture failure')}
 assert.equal((await launchEnhancementInstaller(f.ctx)).ok,false)
})
