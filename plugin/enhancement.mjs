// Local launch is an explicit user gesture. No backend shell or process API.
const installerKey='enhancement.installerPath'
export function validInstallerPath(value) {
  if(typeof value!=='string' || value.length>1024 || !/^[A-Za-z]:[\\/]/.test(value) || /[\x00-\x1f<>"|?*:%!]/.test(value.slice(2))) return false
  const parts=value.slice(3).split(/[\\/]/)
  if(parts.some(part=>!part || part==='.' || part==='..' || /[. ]$/.test(part) || /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(part))) return false
  return /^NeoComposerSetup\.cmd$/i.test(parts.at(-1))
}
export async function chooseEnhancementInstaller(ctx) {
  if(typeof ctx.os?.pickOpenPath!=='function') return {ok:false,reason:'Local File Picker Is Unavailable'}
  try {
    const path=await ctx.os.pickOpenPath({title:'Select The Trusted Neo Composer Installer',filters:[{name:'Neo Composer Installer',extensions:['cmd']}]})
    if(path===null) return {ok:false,reason:'Selection Cancelled'}
    if(!validInstallerPath(path)) return {ok:false,reason:'Choose A Local NeoComposerSetup.cmd File'}
    ctx.storage.set(installerKey,path)
    if(ctx.storage.get(installerKey,null)!==path) return {ok:false,reason:'Installer Selection Was Not Saved'}
    return {ok:true,path}
  } catch {return {ok:false,reason:'Installer Selection Could Not Be Saved'}}
}
export async function launchEnhancementInstaller(ctx,mode='apply') {
  const names={apply:'NeoComposerSetup.cmd',check:'NeoComposerCheck.cmd',rollback:'NeoComposerUninstall.cmd'}
  if(!Object.hasOwn(names,mode)) return {ok:false,reason:'Unsupported Installer Action'}
  try {
    const saved=ctx.storage.get(installerKey,null)
    if(!validInstallerPath(saved)) return {ok:false,reason:'Select A Trusted Local Installer First'}
    if(typeof ctx.os?.openExternal!=='function') return {ok:false,reason:'Local Launch Is Unavailable'}
    const path=saved.replace(/NeoComposerSetup\.cmd$/i,names[mode])
    if(await ctx.os.openExternal(path)!==true) return {ok:false,reason:'Installer Open Request Failed'}
    // The SDK acknowledges an open request, NOT process exit or installation.
    return {ok:true,state:'requested',installed:false}
  } catch {return {ok:false,reason:'Installer Open Request Failed'}}
}
export function createEnhancementView({host,jsx,useRef,useState,Button,portableSupported}) {
  return function EnhancementSettings({ctx}) {
    const [path,setPath]=useState(()=>{try{return ctx.storage.get(installerKey,'')}catch{return ''}})
    const [notice,setNotice]=useState(''), [busy,setBusy]=useState(false), pending=useRef(false)
    const operate=async action=>{
      if(pending.current)return
      pending.current=true;setBusy(true);setNotice('')
      try {
        const result=action==='choose'?await chooseEnhancementInstaller(ctx):await launchEnhancementInstaller(ctx,action)
        if(result.path)setPath(result.path)
        setNotice(result.ok?(action==='choose'?'Installer Selected. Launch Only A Package You Trust.':'Open Request Sent. Check The Installer Result; Installation Is Not Yet Confirmed.'):result.reason)
      } finally {pending.current=false;setBusy(false)}
    }
    const native=host.composer?.behaviorVersion===2, strict=native && host.composer?.strictSteeringVersion===1
    return jsx('section',{'aria-label':'Native Enhancement',style:{display:'grid',gap:12,padding:16,border:'1px solid var(--ui-stroke-secondary)',borderRadius:8},children:[
      jsx('h3',{style:{fontWeight:600},children:'Native Enhancement'}),
      jsx('p',{children:native?'Native Suggestions: Loaded':portableSupported(host)?'SDK Suggestions: Available · Native Enhancement: Not Loaded':'Suggestions: Host Support Required'}),
      jsx('p',{style:{color:'var(--ui-text-secondary)'},children:strict?'Strict Steering UI: Present — Backend Support Still Requires Verification':'Strict Steering UI: Not Present · Native Shortcuts Are Unchanged'}),
      jsx('p',{style:{color:'var(--ui-text-secondary)'},children:'One-Time Setup: Select NeoComposerSetup.cmd From Your Trusted Enhancement Package. Future Actions Use That Local Installer, Not The Remote Agent Backend.'}),
      jsx('code',{style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'},children:path||'No Local Installer Selected'}),
      jsx('div',{style:{display:'flex',flexWrap:'wrap',gap:8},children:[
        jsx(Button,{variant:'outline',disabled:busy||typeof ctx.os?.pickOpenPath!=='function',onClick:()=>operate('choose'),children:'Select Local Installer'}),
        jsx(Button,{disabled:busy||!validInstallerPath(path)||typeof ctx.os?.openExternal!=='function',onClick:()=>operate('apply'),children:'Install / Repair'}),
        jsx(Button,{variant:'outline',disabled:busy||!validInstallerPath(path)||typeof ctx.os?.openExternal!=='function',onClick:()=>operate('check'),children:'Check Installation'}),
        jsx(Button,{variant:'ghost',disabled:busy||!validInstallerPath(path)||typeof ctx.os?.openExternal!=='function',onClick:()=>operate('rollback'),children:'Uninstall Enhancement'})
      ]}),
      jsx('p',{role:'status',style:{color:'var(--ui-text-secondary)'},children:notice}),
      jsx('p',{style:{fontSize:12,color:'var(--ui-text-secondary)'},children:'Unknown Hermes Versions Are Refused. No Forced Restart, Downgrade Or Automatic Patching. Opening The Installer Does Not Prove It Finished.'})
    ]})
  }
}
