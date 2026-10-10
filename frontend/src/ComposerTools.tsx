import {useEffect,useId,useRef,useState} from 'react';
import type {KeyboardEvent} from 'react';
import {Plus,Sparkles,LockKeyhole,Globe,ChevronDown,Check,FileText,FolderPlus,ListChecks,SlidersHorizontal,BookOpen,ArrowUpRight} from 'lucide-react';
import './composer-tools.css';

export type ComposerAction='files'|'sources'|'task'|'preferences'|'skills';
export type ComposerToolsProps={
 choice:string;
 providers:Array<{id:string;label:string}>;
 cloudEnabled:boolean;
 cloudBlocked:boolean;
 disabled:boolean;
 webConfigured:boolean;
 webAllowed:boolean;
 sourceLabel?:string;
 onChooseModel:(value:string)=>void;
 onToggleWeb:()=>void;
 onAction:(action:ComposerAction)=>void;
};
type Menu='actions'|'models';

/** Web preference is explicit and persistent; cloud model grants have their own flow. */
export function ComposerTools({choice,providers,cloudEnabled,cloudBlocked,disabled,webConfigured,webAllowed,sourceLabel,onChooseModel,onToggleWeb,onAction}:ComposerToolsProps){
 const [menu,setMenu]=useState<Menu|null>(null);
 const root=useRef<HTMLDivElement>(null),actions=useRef<HTMLButtonElement>(null),models=useRef<HTMLButtonElement>(null),popup=useRef<HTMLDivElement>(null);
 const id=useId();
 const isLocal=choice==='local';
 const provider=providers.find(p=>'cloud:'+p.id===choice);
 const modelLabel=isLocal?'Nur lokal':provider?'Auto + '+provider.label:cloudEnabled&&!cloudBlocked?'Auto · Lokal + Cloud':'Auto · Lokal';
 const webDisabled=disabled||isLocal||!webConfigured;
 const webHint=isLocal?'Im Modus Nur lokal bleibt die Websuche ausgeschaltet.':!webConfigured?'Websuche ist noch nicht eingerichtet.':webAllowed?'Automatische Webrecherche ausschalten.':'Automatische Webrecherche einschalten.';
 function close(restore=false){const trigger=menu==='actions'?actions.current:models.current;setMenu(null);if(restore)trigger?.focus()}
 function toggle(next:Menu){setMenu(current=>current===next?null:next)}
 useEffect(()=>{if(!menu)return;popup.current?.querySelector<HTMLButtonElement>('button[role^="menuitem"]:not(:disabled)')?.focus();const outside=(event:PointerEvent)=>{if(!root.current?.contains(event.target as Node))setMenu(null)};document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside)},[menu]);
 useEffect(()=>{if(disabled)setMenu(null)},[disabled]);
 function keys(event:KeyboardEvent<HTMLDivElement>){
  if(!menu)return;
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return}
  if(event.key==='Tab'){close(true);return}
  if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
  const items=Array.from(popup.current?.querySelectorAll<HTMLButtonElement>('button[role^="menuitem"]:not(:disabled)')||[]);
  if(!items.length)return;
  event.preventDefault();const current=items.indexOf(document.activeElement as HTMLButtonElement);
  const next=event.key==='Home'?0:event.key==='End'?items.length-1:event.key==='ArrowDown'?(current+1)%items.length:(current-1+items.length)%items.length;
  items[next]?.focus();
 }
 function triggerKeys(event:KeyboardEvent<HTMLButtonElement>,next:Menu){if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();setMenu(next)}}
 function action(value:ComposerAction){close(true);onAction(value)}
 function choose(value:string){close(true);onChooseModel(value)}
 return <div className="composer-tools" ref={root} onKeyDown={keys}>
  <button ref={actions} className="composer-tool composer-add" type="button" aria-label="Aktionen und Anhänge" aria-haspopup="menu" aria-expanded={menu==='actions'} aria-controls={menu==='actions'?id+'-actions':undefined} disabled={disabled} onClick={()=>toggle('actions')} onKeyDown={event=>triggerKeys(event,'actions')} title="Dateien, Quellen, Aufgaben und Antwortstil"><Plus size={19}/></button>
  <button ref={models} className="composer-tool composer-model" type="button" aria-label="Modellwahl" aria-haspopup="menu" aria-expanded={menu==='models'} aria-controls={menu==='models'?id+'-models':undefined} disabled={disabled} onClick={()=>toggle('models')} onKeyDown={event=>triggerKeys(event,'models')}><span className="composer-model-icon">{isLocal?<LockKeyhole size={14}/>:<Sparkles size={14}/>}</span><span>{modelLabel}</span><ChevronDown className="composer-chevron" size={13}/></button>
  {sourceLabel&&<button className="composer-tool composer-source" type="button" disabled={disabled} onClick={()=>onAction('sources')} aria-label="Quellen für dieses Gespräch öffnen"><BookOpen size={14}/><span>{sourceLabel}</span></button>}
  <button className={'composer-tool composer-web'+(webAllowed?' is-enabled':'')} type="button" aria-label={webAllowed?'Websuche aktiviert':'Websuche'} aria-pressed={webAllowed} disabled={webDisabled} title={webHint} onClick={onToggleWeb}><Globe size={15}/><span>{webAllowed?'Websuche an':'Websuche'}</span>{webAllowed&&<Check size={13}/>}</button>
  {menu&&<div className="composer-popover" ref={popup} id={id+'-'+menu} role="menu" aria-label={menu==='actions'?'Aktionen und Anhänge':'Modellwahl'}>
   <div className="composer-popover-heading">{menu==='actions'?'Mit deinem Gespräch weiterarbeiten':'Wie soll die KI antworten?'}</div>
   {menu==='actions'?<>
    <button type="button" role="menuitem" onClick={()=>action('files')}><FileText size={19}/><span><strong>Datei erstellen</strong><small>Antwort als Word oder Präsentation ausarbeiten</small></span></button>
    <button type="button" role="menuitem" onClick={()=>action('sources')}><FolderPlus size={19}/><span><strong>{sourceLabel?'Quellen ansehen':'Mit Projektquellen arbeiten'}</strong><small>{sourceLabel?'Unterlagen für dieses Gespräch verwalten':'Im Projektgespräch verfügbar'}</small></span></button>
    <button type="button" role="menuitem" onClick={()=>action('task')}><ListChecks size={19}/><span><strong>Aufgabe planen</strong><small>Aus einer Idee einen kontrollierten Ablauf machen</small></span></button>
    <button type="button" role="menuitem" onClick={()=>action('skills')}><Sparkles size={19}/><span><strong>Skill einsetzen</strong><small>Eine aktivierte Regel für diese Anfrage aufrufen</small></span></button>
    <button type="button" role="menuitem" onClick={()=>action('preferences')}><SlidersHorizontal size={19}/><span><strong>Antwortstil einstellen</strong><small>Sprache, Länge und Darstellung einstellen</small></span></button>
   </>:<>
    <button type="button" role="menuitemradio" aria-label="Auto" aria-checked={choice==='auto'} onClick={()=>choose('auto')}><Sparkles size={19}/><span><strong>Auto</strong><small>{cloudBlocked?'Private Quellen bleiben lokal':cloudEnabled?'Lokal oder Cloud nach deinen Routingregeln':'Lokales Modell · Cloud am Server ausgeschaltet'}</small></span>{choice==='auto'&&<Check size={17}/>}</button>
    <button type="button" role="menuitemradio" aria-label="Nur lokal" aria-checked={isLocal} onClick={()=>choose('local')}><LockKeyhole size={19}/><span><strong>Nur lokal</strong><small>Lokales Modell, ohne Cloud und Websuche</small></span>{isLocal&&<Check size={17}/>}</button>
    {cloudEnabled&&providers.length>0&&<div className="composer-menu-divider">Weitere Cloudanbieter</div>}
    {cloudEnabled&&providers.map(item=><button key={item.id} type="button" role="menuitemradio" aria-label={'Auto + '+item.label} aria-checked={choice==='cloud:'+item.id} disabled={cloudBlocked} onClick={()=>choose('cloud:'+item.id)}><ArrowUpRight size={19}/><span><strong>Auto + {item.label}</strong><small>{cloudBlocked?'Für Projekt- und Wissensgespräche nicht verfügbar':'Neues Gespräch · Anbieter und Übertragung bestätigen'}</small></span>{choice==='cloud:'+item.id&&<Check size={17}/>}</button>)}
   </>}
  </div>}
 </div>;
}
