import {useEffect,useState,useMemo,lazy,Suspense} from 'react';
import type {ArtifactSeed} from './ArtifactsPanel';
import type {TaskSeed} from './TasksPanel';
import {FileDropzone} from './FileDropzone';
import {uploadProjectSource} from './projectUpload';
import {PreferencesPanel} from './PreferencesPanel';
import './workspace.css';
const ArtifactsPanel=lazy(()=>import('./ArtifactsPanel').then(m=>({default:m.ArtifactsPanel})));
const TasksPanel=lazy(()=>import('./TasksPanel').then(m=>({default:m.TasksPanel})));
type API=(path:string,method?:string,body?:unknown)=>Promise<any>;
export type WorkTab='files'|'sources'|'preferences'|'task';
type Source={id:string;name:string;revision:number;sha256:string;status:string};
type Project={id:string;name:string;archived:boolean;kind?:string};
export function WorkspacePanel({api,csrf,conversationId,projectId,memoryScope,tab,onTab,onClose,seed,taskSeed,onOpenProject,onOpenTasks,onTaskCreated}:{api:API;csrf:string;conversationId?:string|null;projectId?:string|null;memoryScope?:string|null;tab:WorkTab;onTab:(tab:WorkTab)=>void;onClose:()=>void;seed?:ArtifactSeed|null;taskSeed?:TaskSeed|null;onOpenProject:(projectId:string,tab:string)=>void;onOpenTasks:()=>void;onTaskCreated?:()=>void}){
 const [projects,setProjects]=useState<Project[]>([]),[target,setTarget]=useState<string|null>(projectId||null),[project,setProject]=useState<Project|null>(null),[sources,setSources]=useState<Source[]>([]),[error,setError]=useState(''),[notice,setNotice]=useState(''),[uploading,setUploading]=useState(false),[createdTask,setCreatedTask]=useState<string|null>(null);
 useEffect(()=>{let active=true;api('/projects').then((rows:Project[])=>{if(active)setProjects(rows)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[api]);
 useEffect(()=>{setTarget(projectId||null);setCreatedTask(null);setNotice('')},[conversationId,projectId]);
 const effectiveTaskSeed=useMemo(()=>taskSeed||{goal:'',project_id:projectId||null},[taskSeed,projectId]);
 useEffect(()=>{if(taskSeed)setCreatedTask(null)},[taskSeed]);
 const [taskStarted,setTaskStarted]=useState(tab==='task');
 useEffect(()=>{if(tab==='task')setTaskStarted(true)},[tab]);
 const sourceProject=target||projectId;
 useEffect(()=>{let active=true;setProject(null);setSources([]);setError('');if(!sourceProject)return;
  const refresh=()=>Promise.all([api('/projects/'+sourceProject),api('/projects/'+sourceProject+'/sources')]).then(([p,s])=>{if(active){setProject(p);setSources(s.filter((row:Source)=>row.status!=='superseded'))}});
  void refresh().catch(e=>{if(active)setError(e.message)});const timer=setInterval(()=>void refresh().catch(()=>{}),3000);return()=>{active=false;clearInterval(timer)};
 },[api,sourceProject]);
 async function upload(files:File[]|null){if(!projectId||!files||uploading)return;setUploading(true);setError('');try{for(const file of Array.from(files)){await uploadProjectSource(projectId,file,csrf);}setSources(await api('/projects/'+projectId+'/sources'));setNotice('Quellen hinzugefügt. Die lokale Verarbeitung läuft; fertige Quellen können für neue Antworten verwendet werden.');}catch(e){setError((e as Error).message)}finally{setUploading(false)}}
 return <aside className="workbench" aria-label="Arbeitsbereich neben dem Chat"><div className="workbench-heading"><div><small>DEIN ARBEITSKONTEXT</small><h2>Gemeinsam weiterarbeiten</h2></div><button aria-label="Arbeitsbereich schließen" onClick={onClose}>×</button></div>
 <div className="workbench-tabs" role="tablist" aria-label="Arbeitsbereich"><button role="tab" aria-selected={tab==='files'} onClick={()=>onTab('files')}>Dateien</button><button role="tab" aria-selected={tab==='sources'} onClick={()=>onTab('sources')}>Quellen</button><button role="tab" aria-selected={tab==='preferences'} onClick={()=>onTab('preferences')}>Vorgaben</button><button role="tab" aria-selected={tab==='task'} onClick={()=>onTab('task')}>Aufgabe</button></div>
 <div className="workbench-content">{error&&<p className="error" role="alert">{error}</p>}{notice&&<p role="status" className="hint">{notice}</p>}
 <section hidden={tab!=='files'} aria-label="Dateien im Arbeitsbereich"><p className="hint">Gespräch und Herkunft bleiben erhalten. Eine Datei wird in einem Projektraum gespeichert.</p>{!projectId&&<label>Datei in Projekt speichern<select aria-label="Datei in Projekt speichern" value={target||''} onChange={e=>setTarget(e.target.value||null)}><option value="">Projektraum auswählen</option>{projects.filter(p=>!p.archived&&p.kind!=='knowledge').map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
 {memoryScope?<p>Öffne für eine Datei ein Projektgespräch und wähle dort die gewünschte Antwort.</p>:project&&sourceProject===target?<Suspense fallback={<p role="status">Dateien laden …</p>}><ArtifactsPanel key={project.id} api={api} project={project} sources={sources.filter(s=>s.status==='ready')} seed={seed} embedded contextLabel={project.name}/></Suspense>:<p className="hint">{target?'Projektraum wird geladen …':'Wähle einen Projektraum für die Datei. Du kannst ihn unter Projekte anlegen.'}</p>}
 </section>
 <section hidden={tab!=='sources'} aria-label="Quellen im Arbeitsbereich"><h3>Quellen für dieses Gespräch</h3>{projectId?<><p className="hint">Bereite Projektquellen können für neue Fragen ausgewählt werden. Tatsächlich verwendete Auszüge stehen bei der Antwort; ein Upload allein bedeutet keine vollständige Berücksichtigung.</p><FileDropzone disabled={uploading||!!project?.archived} onFiles={upload} label="Quellen im Chat hochladen"/><ul className="workspace-source-list">{sources.map(s=><li key={s.id}><strong>{s.name}</strong><small>{s.status==='ready'?'Verarbeitet':s.status==='failed'?'Verarbeitung fehlgeschlagen':'In Verarbeitung'} · Version {s.revision}</small></li>)}</ul>{!sources.length&&<p className="hint">Noch keine Projektquellen vorhanden.</p>}<button onClick={()=>onOpenProject(projectId,'sources')}>Projektquellen und Webseiten verwalten</button></>:<p className="hint">{memoryScope?'Dieses Wissensgespräch verwendet den gewählten Obsidian-Kontext.':'Ein freies Gespräch hat keine Projektquellen. Öffne einen Projektraum, um Unterlagen als Kontext zu verwenden.'}</p>}{!projectId&&!memoryScope&&<div className="source-project-choices">{projects.filter(p=>!p.archived&&p.kind!=='knowledge').map(p=><button key={p.id} onClick={()=>onOpenProject(p.id,'sources')}><strong>{p.name}</strong><span>Quellen im Projekt verwalten →</span></button>)}{!projects.some(p=>!p.archived&&p.kind!=='knowledge')&&<p className="hint">Lege unter Projekte zuerst einen Projektraum an.</p>}</div>}</section>
 <section hidden={tab!=='preferences'} aria-label="Vorgaben im Arbeitsbereich">{conversationId?<PreferencesPanel api={api} conversationId={conversationId}/>:<PreferencesPanel api={api}/>}</section>
 <section hidden={tab!=='task'} aria-label="Aufgaben im Arbeitsbereich">{createdTask&&<div role="status" className="workspace-success"><strong>Aufgabe gespeichert und pausiert.</strong><p>Prüfe sie in der Aufgabenübersicht, bevor du sie aktivierst.</p><button onClick={onOpenTasks}>Aufgabenübersicht öffnen</button></div>}<Suspense fallback={<p role="status">Aufgabeneditor lädt …</p>}>{taskStarted&&!createdTask&&<TasksPanel key={JSON.stringify([conversationId,effectiveTaskSeed.project_id,effectiveTaskSeed.goal])} api={api} seed={effectiveTaskSeed} embedded onCreated={id=>{setCreatedTask(id);onTaskCreated?.()}}/>}</Suspense></section>
 </div></aside>;
}
