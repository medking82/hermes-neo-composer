// SDK-only mode: explicit preview and acknowledged insertion, never send.
const portableAtoms = ['focusedSessionId','focusedStoredSessionId','focusedSessionOwner','connectionId','profile','busy']
export const portableSupported = host => typeof host.activeConnectionId==='function' && typeof host.composer?.getDraft==='function' && typeof host.composer?.insertText==='function' && portableAtoms.every(key=>typeof host.state?.[key]?.get==='function')
export function readPortableContext(host) {
  if(!portableSupported(host)) return null
  const read=key=>host.state[key].get()
  const connectionId=host.activeConnectionId(), sessionId=read('focusedSessionId'), storedId=read('focusedStoredSessionId'), busy=read('busy')
  const rawProfile=read('profile'), owner=read('focusedSessionOwner')
  const profile=typeof rawProfile==='string'?(rawProfile||'default'):null
  if(!owner || Array.isArray(owner) || typeof owner!=='object' || !profile || typeof owner.profile!=='string') return null
  if(![connectionId,sessionId,storedId].every(value=>typeof value==='string' && value.length>0) || typeof busy!=='boolean') return null
  if(connectionId!==owner.connectionId || profile!==(owner.profile||'default')) return null
  return Object.freeze({connectionId,profile,sessionId,storedId,busy})
}
export const samePortableContext = (host,context) => !!context && JSON.stringify(readPortableContext(host))===JSON.stringify(context)
const portableOwnerMatches = (host,context) => host.activeConnectionId()===context.connectionId && (host.state.profile.get()||'default')===context.profile
export async function insertPortableOffer(host,context,controller) {
  if(!context || context.busy || !samePortableContext(host,context)) return {ok:false,reason:'Context Changed'}
  const offer=controller?.capture()
  if(!offer) return {ok:false,reason:'Suggestion Is No Longer Available'}
  const draft=await host.composer.getDraft(context.storedId)
  if(draft!=='' || !samePortableContext(host,context) || !offer.current()) return {ok:false,reason:'Draft Or Context Changed'}
  if(typeof offer.validate!=='function' || await offer.validate()!==true) return {ok:false,reason:'Suggestion Is No Longer Current'}
  if(await host.composer.getDraft(context.storedId)!=='' || !samePortableContext(host,context) || !offer.current()) return {ok:false,reason:'Draft Or Context Changed'}
  const applied=await host.composer.insertText(context.storedId,offer.text,{mode:'inline'})
  if(applied!==true) return {ok:false,reason:'Draft Was Not Inserted'}
  return {ok:true,durable:offer.commit()}
}
export function createPortableSession({host,ctx,context,createController,onChange}) {
  let disposed=false,started=false,controller=null,inserting=false
  const current=()=>!disposed && !!context && !context.busy && samePortableContext(host,context)
  const publish=update=>{if(current()) onChange(update)}
  const request=async(path,body)=>{
    if(path==='/decision') {
      if(!portableOwnerMatches(host,context)) throw Error('Owner Changed')
    } else {
      if(!current() || await host.composer.getDraft(context.storedId)!=='' || !current()) throw Error('Draft Or Context Changed')
    }
    const result=await ctx.rest(path,{method:'POST',body})
    if(path!=='/decision' && !current()) throw Error('Context Changed')
    return result
  }
  return {
    async start(){
      if(started || !current()) return
      started=true;publish({phase:'checking',text:null})
      try {
        const view=await ctx.rest('/settings')
        if(!current()) return
        if(view?.settings?.enabled!==true || !view?.selection?.route) {publish({phase:'paused',text:null});return}
        if(await host.composer.getDraft(context.storedId)!=='' || !current()) {publish({phase:'draft',text:null});return}
        controller=createController({context,request,publish:text=>publish({phase:text?'ready':'idle',text}),onSettled:listener=>typeof ctx.onEvent==='function'?ctx.onEvent('session.info',event=>{
          if(current() && event.session_id===context.sessionId && event.payload?.running===false) listener()
        }):()=>{}},ctx.storage)
        controller.update({enabled:true,empty:true})
      } catch {publish({phase:'unavailable',text:null})}
    },
    async insert(){
      if(inserting) return {ok:false,reason:'Insertion Already Pending'}
      inserting=true
      try {return await insertPortableOffer(host,context,controller)}
      catch {return {ok:false,reason:'Insertion Could Not Be Confirmed'}}
      finally {inserting=false}
    },
    dismiss(){return current() && !!controller?.decide('dismissed')},
    dispose(){disposed=true;controller?.dispose()}
  }
}
export function createPortableWidget({host,jsx,useValue,useEffect,useRef,useState,Button,Popover,PopoverTrigger,PopoverContent,createController}) {
  return function PortableSuggestions({ctx}) {
    useValue(host.state.focusedSessionId)
    useValue(host.state.focusedStoredSessionId)
    useValue(host.state.focusedSessionOwner)
    useValue(host.state.connectionId)
    useValue(host.state.profile)
    useValue(host.state.busy)
    const [open,setOpen]=useState(false), [revision,setRevision]=useState(0), [view,setView]=useState({phase:'idle',text:null}), [notice,setNotice]=useState(''), [pending,setPending]=useState(false)
    const ref=useRef(null), context=readPortableContext(host), key=JSON.stringify(context)
    useEffect(()=>{
      setView({phase:'idle',text:null});setNotice('');setPending(false)
      if(!open || !context || context.busy) return
      const session=createPortableSession({host,ctx,context,createController,onChange:setView})
      ref.current=session;void session.start()
      return ()=>{if(ref.current===session)ref.current=null;session.dispose()}
    },[ctx,open,key,revision])
    const insert=async()=>{
      const session=ref.current;if(!session || pending)return
      setPending(true);setNotice('')
      const result=await session.insert()
      if(ref.current!==session)return
      setPending(false);setNotice(result.ok?(result.durable?'Inserted As Draft':'Inserted As Draft; Decision Was Not Saved'):result.reason)
    }
    const hints={checking:'Checking Prediction Settings…',paused:'Prediction Is Paused. Check Neo Composer Settings.',draft:'Keep The Draft Empty To Request A Suggestion.',idle:'No Suggestion For This Context Yet.',unavailable:'Prediction Backend Is Unavailable.'}
    return jsx(Popover,{open,onOpenChange:setOpen,children:[
      jsx(PopoverTrigger,{asChild:true,children:jsx(Button,{variant:'ghost',size:'sm','aria-label':'Neo Composer Suggestions',children:'Neo Composer · Suggestions'})}),
      jsx(PopoverContent,{align:'end',style:{width:340,maxWidth:'calc(100vw - 24px)',display:'grid',gap:12},children:[
        jsx('strong',{children:'Neo Composer Suggestions'}),
        jsx('p',{style:{color:'var(--ui-text-secondary)'},children:'SDK Compatibility Mode · Native Shortcuts Are Unchanged'}),
        jsx('p',{role:'status',style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'},children:!context?'Select A Chat Owned By The Active Gateway.':context.busy?'Suggestions Pause While The Chat Is Working.':view.text||hints[view.phase]||hints.idle}),
        jsx('div',{style:{display:'flex',flexWrap:'wrap',gap:8},children:[
          jsx(Button,{disabled:!view.text||pending||!context||context.busy,onClick:insert,children:pending?'Inserting…':'Insert As Draft'}),
          jsx(Button,{variant:'outline',disabled:!view.text||pending,onClick:()=>{if(ref.current?.dismiss())setNotice('Dismissed For This Context')},children:'Dismiss'}),
          jsx(Button,{variant:'ghost',disabled:pending,onClick:()=>setRevision(value=>value+1),children:'Refresh'})
        ]}),
        jsx('p',{role:'status',style:{color:'var(--ui-text-secondary)'},children:notice})
      ]})
    ]})
  }
}
