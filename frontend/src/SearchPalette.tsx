import {useEffect,useId,useRef,useState} from 'react';
import type {KeyboardEvent} from 'react';
import {Search,X,MessageSquare,Folder,FileText,BookOpen,ListChecks,Library,ArrowUpRight,LoaderCircle} from 'lucide-react';
import './search-palette.css';

export type SearchKind='conversation'|'project'|'artifact'|'source'|'task'|'knowledge';
export type SearchResult={kind:SearchKind;id:string;title:string;subtitle:string;project_id?:string|null;conversation_id?:string|null;matched_in:'title'|'content'};
type SearchResponse={query:string;results:SearchResult[];has_more:boolean;limit:number};
type Props={api:(path:string,method?:string,body?:unknown)=>Promise<any>;onClose:()=>void;onSelect:(result:SearchResult)=>void};
const filters:Array<{kind:SearchKind|'all';label:string}>=[{kind:'all',label:'Alles'},{kind:'conversation',label:'Gespräche'},{kind:'project',label:'Projekte'},{kind:'artifact',label:'Dateien'},{kind:'source',label:'Quellen'},{kind:'task',label:'Aufgaben'},{kind:'knowledge',label:'Wissen'}];
const labels:Record<SearchKind,string>={conversation:'Gespräch',project:'Projekt',artifact:'Datei',source:'Quelle',task:'Aufgabe',knowledge:'Wissensquelle'};
const icons={conversation:MessageSquare,project:Folder,artifact:FileText,source:BookOpen,task:ListChecks,knowledge:Library};

/** Read-only local search. Query text lives only in this mounted dialog. */
export function SearchPalette({api,onClose,onSelect}:Props){
 const [query,setQuery]=useState(''),[kind,setKind]=useState<SearchKind|'all'>('all');
 const [response,setResponse]=useState<{key:string;data:SearchResponse}|null>(null),[failure,setFailure]=useState<{key:string;message:string}|null>(null),[active,setActive]=useState(0),[retry,setRetry]=useState(0);
 const input=useRef<HTMLInputElement>(null),dialog=useRef<HTMLElement>(null),generation=useRef(0);
 const id=useId(),trimmed=query.trim(),key=kind+'\n'+trimmed,valid=trimmed.length>=2;
 const data=response?.key===key?response.data:null,error=failure?.key===key?failure.message:null;
 const results=data?.results||[],loading=valid&&!data&&!error;
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null;input.current?.focus();return()=>{if(previous?.isConnected)previous.focus()}},[]);
 useEffect(()=>{
  const request=++generation.current;
  setActive(0);setFailure(null);
  if(!valid)return;
  const timer=window.setTimeout(()=>{
   api('/workspace/search?q='+encodeURIComponent(trimmed)+'&kind='+kind).then((value:SearchResponse)=>{
    if(generation.current===request)setResponse({key,data:value});
   }).catch((cause:unknown)=>{
    if(generation.current===request)setFailure({key,message:cause instanceof Error?cause.message:'Die Suche konnte nicht geladen werden.'});
   });
  },200);
  return()=>{window.clearTimeout(timer);generation.current++};
 },[api,trimmed,kind,key,valid,retry]);
 useEffect(()=>{if(results.length)document.getElementById(id+'-result-'+active)?.scrollIntoView({block:'nearest'})},[active,results.length,id]);
 function clearResults(){generation.current++;setResponse(null);setFailure(null);setActive(0)}
 function changeQuery(value:string){if(value.trim()!==trimmed)clearResults();setQuery(value)}
 function keys(event:KeyboardEvent<HTMLElement>){
  if(event.nativeEvent.isComposing)return;
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();onClose();return}
  if(event.key==='Tab'){
   const controls=Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),[tabindex="0"]')||[]);
   const first=controls[0],last=controls[controls.length-1];
   if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}
   else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}
   return;
  }
  if(event.target!==input.current||!results.length)return;
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();setActive(current=>(current+(event.key==='ArrowDown'?1:-1)+results.length)%results.length)}
  else if(event.key==='Home'||event.key==='End'){event.preventDefault();setActive(event.key==='Home'?0:results.length-1)}
  else if(event.key==='Enter'){event.preventDefault();onSelect(results[Math.min(active,results.length-1)])}
 }
 return <div className="search-palette-overlay" onClick={event=>{if(event.target===event.currentTarget)onClose()}}>
  <section className="search-palette" ref={dialog} role="dialog" aria-modal="true" aria-labelledby={id+'-title'} onKeyDown={keys}>
   <header className="search-palette-header"><div><span className="search-palette-eyebrow">DEIN ARBEITSRAUM</span><h2 id={id+'-title'}>Suchen und weiterarbeiten</h2></div><button type="button" aria-label="Suche schließen" onClick={onClose}><X size={20}/></button></header>
   <div className="search-palette-input"><Search size={21} aria-hidden="true"/><input ref={input} aria-label="Arbeitsraum durchsuchen" role="combobox" aria-autocomplete="list" aria-expanded={valid} aria-controls={id+'-results'} aria-activedescendant={results.length?id+'-result-'+Math.min(active,results.length-1):undefined} aria-describedby={id+'-hint'} value={query} maxLength={120} autoComplete="off" spellCheck={false} placeholder="Gespräche, Dateien, Aufgaben …" onChange={event=>changeQuery(event.target.value)}/>{query&&<button type="button" aria-label="Suchtext leeren" onClick={()=>{changeQuery('');input.current?.focus()}}><X size={16}/></button>}</div>
   <div className="search-palette-filters" role="group" aria-label="Suchbereich">{filters.map(filter=><button key={filter.kind} type="button" aria-pressed={kind===filter.kind} onClick={()=>{if(kind!==filter.kind){clearResults();setKind(filter.kind)}input.current?.focus()}}>{filter.label}</button>)}</div>
   <div className="search-palette-content" aria-busy={loading}>
    <div className="search-palette-status" role="status" aria-live="polite">{!valid?'Gib mindestens zwei Zeichen ein.':loading?<><LoaderCircle size={17} className="search-palette-loading"/>Suche im lokalen Arbeitsraum …</>:error?'Suche nicht verfügbar':results.length?results.length+' Treffer'+(data?.has_more?' · weitere Treffer vorhanden':''):'Keine passenden Treffer'}</div>
    {error&&<div className="search-palette-error"><p>{error}</p><button type="button" onClick={()=>setRetry(value=>value+1)}>Erneut versuchen</button></div>}
    {!valid&&<p className="search-palette-explanation">Finde Gespräche, Projektnamen, Dateititel, Quellen und Aufgaben und öffne sie direkt. Die Suche bleibt lokal und verändert keine Daten.</p>}
    {valid&&data&&!results.length&&<p className="search-palette-explanation">Versuche einen anderen Begriff oder wähle einen anderen Suchbereich.</p>}
    <div id={id+'-results'} className="search-palette-results" role="listbox" aria-label="Suchergebnisse">{results.map((result,index)=>{const Icon=icons[result.kind];return <div key={result.kind+':'+result.id} id={id+'-result-'+index} className={'search-palette-result'+(index===active?' is-active':'')} role="option" aria-selected={index===active} onPointerMove={()=>setActive(index)} onMouseDown={event=>event.preventDefault()} onClick={()=>onSelect(result)}><span className="search-palette-result-icon"><Icon size={20} aria-hidden="true"/></span><div className="search-palette-result-copy"><span className="search-palette-result-kind">{labels[result.kind]}{result.matched_in==='content'?' · Inhaltstreffer':''}</span><strong>{result.title||'Ohne Titel'}</strong>{result.subtitle&&<p>{result.subtitle}</p>}</div><ArrowUpRight size={17} aria-hidden="true"/></div>})}</div>
    {data?.has_more&&<p className="search-palette-explanation">Grenze deine Suche ein, um weitere Treffer zu finden.</p>}
   </div>
   <footer id={id+'-hint'} className="search-palette-footer"><span>↑ ↓ auswählen · Enter öffnen</span><span>Esc schließen · nur lokal</span></footer>
  </section>
 </div>;
}
