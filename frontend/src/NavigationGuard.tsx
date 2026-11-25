import {createPortal} from 'react-dom';
import './NavigationGuard.css';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {useDialogAccessibility,useLegacyDialogAccessibility} from './useDialogAccessibility';
const drafts=new Map<symbol,string>();
const navigationEvent='hub-request-navigation';
export function useUnsavedChanges(dirty:boolean,label:string,revision:unknown=dirty){
 const key=useRef(Symbol(label));
 useEffect(()=>{if(dirty)drafts.set(key.current,label);else drafts.delete(key.current);return()=>{drafts.delete(key.current)}},[dirty,label,revision]);
}
export function useEditorDraft(active:boolean,value:unknown,label:string){
 const serialized=JSON.stringify(value),baseline=useRef<string|null>(null);
 if(!active)baseline.current=null;else if(baseline.current===null)baseline.current=serialized;
 useUnsavedChanges(active&&serialized!==baseline.current,label,serialized);
}
export function hasUnsavedChanges(){return drafts.size>0}
export function guardNavigation(run:()=>void){
 if(!drafts.size){run();return}
 window.dispatchEvent(new CustomEvent(navigationEvent,{detail:run}));
}
export function NavigationGuard({children}:{children:ReactNode}){
 useLegacyDialogAccessibility();
 const [pending,setPending]=useState<(()=>void)|null>(null),[labels,setLabels]=useState<string[]>([]);
 const dialog=useRef<HTMLDivElement>(null);
 useDialogAccessibility(dialog,!!pending,()=>setPending(null));
 useEffect(()=>{const request=(event:Event)=>{setLabels([...new Set(drafts.values())]);setPending(()=>(event as CustomEvent<()=>void>).detail)};const unload=(event:BeforeUnloadEvent)=>{if(drafts.size){event.preventDefault();event.returnValue=''}};window.addEventListener(navigationEvent,request);window.addEventListener('beforeunload',unload);return()=>{window.removeEventListener(navigationEvent,request);window.removeEventListener('beforeunload',unload)}},[]);
 return <div className="navigation-guard-root" onClickCapture={event=>{
  if(!drafts.size||pending)return;
  const button=(event.target as HTMLElement).closest<HTMLElement>('button,a');if(!button||button.dataset.localNavigationGuard==='true')return;
  if(button.closest('.settings-tabs')&&(button.getAttribute('aria-pressed')==='true'||[...drafts.values()].every(label=>label==='Persönliches Profil')))return;
  if((button.closest('.modal')&&(/^(Abbrechen|Schließen|Zurück zur Übersicht)$/.test(button.textContent?.trim()||'')||/schließen/i.test(button.getAttribute('aria-label')||'')))||button.closest('.sidebar nav,.history,.settings-tabs,.room-tabs')||button.matches('.sidebar .new,.workbench-heading button')||button.dataset.navigation==='true'){
   event.preventDefault();event.stopPropagation();guardNavigation(()=>button.click());
  }
 }}>{children}{pending&&createPortal(<div className="modal navigation-confirm"><div ref={dialog} role="dialog" aria-modal="true" aria-label="Ungespeicherte Änderungen" tabIndex={-1}><h2>Änderungen behalten?</h2><p>Deine Änderungen in {labels.join(', ')} sind noch nicht gespeichert.</p><p>Bleibe hier, um sie zu speichern, oder gehe ohne Speichern weiter. Gesicherte Aufgabenentwürfe bleiben in diesem Browser-Tab wiederaufnehmbar.</p><div className="dialog-actions"><button type="button" onClick={()=>setPending(null)}>Weiter bearbeiten</button><button type="button" onClick={()=>{const next=pending;drafts.clear();setPending(null);next()}}>Ohne Speichern weiter</button></div></div></div>,document.body)}</div>;
}
