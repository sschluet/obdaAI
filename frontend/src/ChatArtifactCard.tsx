import {useEffect,useState} from 'react';
export type ChatArtifact={project_id:string|null;conversation_id?:string|null;artifact_id:string;revision:number;kind:string;requires_review:boolean};
type ReadyFile={artifact_id:string;revision:number;status:string;error?:string|null;output?:{parts?:{pages:number}[];pdf_export?:unknown}};
export function ChatArtifactCard({artifact,api,onOpen}:{artifact:ChatArtifact;api:(path:string)=>Promise<any>;onOpen:()=>void}){
 const [row,setRow]=useState<ReadyFile|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const prefix=artifact.project_id?'/projects/'+artifact.project_id+'/artifacts':'/conversations/'+artifact.conversation_id+'/artifacts';
 const base=prefix+'/'+artifact.artifact_id+'/versions/'+artifact.revision;
 useEffect(()=>{let stopped=false,timer:ReturnType<typeof setTimeout>;setRow(null);setError('');
  async function refresh(){try{const rows:ReadyFile[]=await api(prefix);if(stopped)return;const next=rows.find(value=>value.artifact_id===artifact.artifact_id&&value.revision===artifact.revision);setRow(next||null);if(!next||['queued','rendering'].includes(next.status))timer=setTimeout(()=>void refresh(),2000)}catch(e){if(!stopped)setError((e as Error).message)}}
  void refresh();return()=>{stopped=true;clearTimeout(timer)};
 },[api,prefix,artifact.artifact_id,artifact.revision,retry]);
 const ready=!!row&&['needs_review','published'].includes(row.status);
 return <article className="citation"><b>Datei · {artifact.kind.toUpperCase()} · Version {artifact.revision}</b><p role="status">{error?'Dateistatus konnte nicht geladen werden.':ready?(row.status==='published'?'Datei bereit und freigegeben.':'Datei bereit. Inhalt vor der weiteren Verwendung prüfen.'):row?.status==='failed'?(row.error||'Dateierstellung fehlgeschlagen.'):row?.status==='cancelled'?'Dateierstellung abgebrochen.':'Datei und Vorschau werden erstellt…'}</p>{ready&&<><a href={'/api'+base+'/download'} download>{row.output?.parts?.length?'Alle PDF-Teile als ZIP herunterladen':'Datei herunterladen'}</a>{row.output?.pdf_export&&<a href={'/api'+base+'/download?pdf=true'} download>Zusätzliches PDF herunterladen</a>}</>}{error&&<button onClick={()=>setRetry(value=>value+1)}>Status erneut laden</button>}<button onClick={onOpen}>Datei im Arbeitsbereich öffnen</button></article>;
}
