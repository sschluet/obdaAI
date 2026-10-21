import {useEffect,useRef,useState} from 'react';
import {Cable,Check,Search} from 'lucide-react';
import {integrationTypes} from './IntegrationRegistryPanel';
import type {IntegrationAPI,IntegrationRow} from './IntegrationRegistryPanel';
import './integration-registry.css';
type Binding={revision:number;integration_ids:string[];selection_mode:'off'|'manual'|'automatic'|'inherit';effective_integration_ids:string[];execution_available:boolean};
export function IntegrationBindingPicker({api,scope,ownerId,onChange,disabled=false,projectContext=false}:{api:IntegrationAPI;scope:'project'|'task'|'conversation';ownerId:string;disabled?:boolean;projectContext?:boolean;onChange?:(binding:Binding)=>void}){
 const [rows,setRows]=useState<IntegrationRow[]>([]),[saved,setSaved]=useState<Binding|null>(null),[ids,setIds]=useState<string[]>([]),[mode,setMode]=useState<Binding['selection_mode']>('automatic'),[search,setSearch]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState(''),[notice,setNotice]=useState('');const lock=useRef(false),generation=useRef(0);
 useEffect(()=>{const version=++generation.current;setLoading(true);setSaved(null);setError('');setNotice('');void Promise.all([api('/integrations'),api('/integration-bindings/'+scope+'/'+ownerId)]).then(([registry,binding])=>{if(version!==generation.current)return;setRows(registry.integrations);setSaved(binding);setIds(binding.integration_ids);setMode(binding.selection_mode)}).catch(e=>{if(version===generation.current)setError(e.message)}).finally(()=>{if(version===generation.current)setLoading(false)});return()=>{generation.current++}},[api,scope,ownerId]);
 async function save(){if(disabled||lock.current||!saved)return;lock.current=true;setBusy(true);setError('');setNotice('');const version=generation.current;try{const binding=await api('/integration-bindings/'+scope+'/'+ownerId,'PUT',{expected_revision:saved.revision,integration_ids:mode==='manual'?ids:[],selection_mode:mode});if(version!==generation.current)return;setSaved(binding);setIds(binding.integration_ids);setMode(binding.selection_mode);setNotice(binding.selection_mode==='automatic'?'Automatische Nutzung gespeichert. Die KI wählt passend zu deiner Anfrage.':binding.selection_mode==='off'?'Integrationen für diesen Bereich ausgeschaltet.':'Integrationsauswahl gespeichert.');onChange?.(binding)}catch(e){if(version===generation.current)setError((e as Error).message)}finally{lock.current=false;setBusy(false)}}
 const changed=!!saved&&(mode!==saved.selection_mode||(mode==='manual'&&JSON.stringify([...ids].sort())!==JSON.stringify([...saved.integration_ids].sort())));
 const visible=rows.filter(row=>(row.name+' '+(row.kind==='gmail'?'Gmail':integrationTypes.find(t=>t.id===row.kind)?.name)).toLocaleLowerCase().includes(search.toLocaleLowerCase()));
 const count=saved?.effective_integration_ids.length||0;
 const summary=loading?'Wird geladen …':!saved?'Nicht verfügbar':saved.selection_mode==='automatic'?'Automatisch · '+count+' verfügbar':saved.selection_mode==='inherit'?'Aus Projekt · '+count+' verfügbar':saved.selection_mode==='off'?'Ausgeschaltet':count+' ausgewählt';
 function describe(row:IntegrationRow){return (row.kind==='gmail'?'Gmail':integrationTypes.find(type=>type.id===row.kind)?.name)+' · '+(!row.enabled?'Deaktiviert':row.kind==='paperless'?(row.execution_available?'Verbunden · lokaler KI-Kontext verfügbar':'Zugang noch prüfen'):'Nutzung innerhalb deiner Freigaben')}
 return <details className="integration-binding-picker"><summary><Cable size={16}/><span>Integrationen <span className="binding-summary">{summary}</span></span></summary>
 {loading?<p role="status">Auswahl wird geladen …</p>:<>
 <p className="hint">Die KI nutzt passende Verbindungen für deine Anfrage. Private Inhalte bleiben lokal; deine Freigaben für Zugriffe und Änderungen gelten weiterhin.</p>
 <div className="binding-modes" role="group" aria-label="Integrationsauswahl">
 <button type="button" disabled={disabled||busy||!saved} aria-pressed={mode==='automatic'} onClick={()=>setMode('automatic')}>Alle automatisch</button>
 <button type="button" disabled={disabled||busy||!saved} aria-pressed={mode==='manual'} onClick={()=>setMode('manual')}>Gezielt auswählen</button>
 <button type="button" disabled={disabled||busy||!saved} aria-pressed={mode==='off'} onClick={()=>setMode('off')}>Keine</button>
 {scope==='conversation'&&(projectContext||saved?.selection_mode==='inherit')&&<button type="button" disabled={disabled||busy||!saved} aria-pressed={mode==='inherit'} onClick={()=>setMode('inherit')}>Projekt übernehmen</button>}
 </div>
 {mode==='automatic'&&<p className="hint">Alle aktivierten Integrationen stehen bereit, auch wenn später weitere hinzukommen. Erst deine Anfrage löst einen passenden Zugriff aus.</p>}
 {mode==='inherit'&&<p className="hint">Es gilt die Auswahl deines Projekts. Mit „Alle automatisch“ oder „Gezielt auswählen“ kannst du sie für dieses Gespräch ändern.</p>}
 {mode==='off'?<p className="hint">Die KI verwendet in diesem Bereich keine Integrationen.</p>:<>
 <label className="registry-search"><Search size={15}/><span className="sr-only">Verbindungen für diese Zuordnung suchen</span><input value={search} placeholder="Verbindungen suchen …" disabled={disabled||busy} onChange={e=>setSearch(e.target.value)}/></label>
 <div className="binding-choices">{visible.map(row=>mode==='manual'?<label key={row.id} className="binding-choice"><input type="checkbox" disabled={disabled||busy||!saved||(!row.enabled&&!ids.includes(row.id))||(!ids.includes(row.id)&&ids.length>=8)} checked={ids.includes(row.id)} onChange={e=>setIds(current=>e.target.checked?[...current,row.id]:current.filter(id=>id!==row.id))}/><span><b>{row.name}</b><small>{describe(row)}</small></span></label>:<div key={row.id} className="binding-choice binding-availability"><Check size={16} aria-hidden="true" className={(mode==='automatic'?row.enabled:saved?.effective_integration_ids.includes(row.id))?'available':'unavailable'}/><span><b>{row.name}</b><small>{describe(row)}</small></span></div>)}</div>
 {!visible.length&&<p className="hint">{rows.length?'Keine passenden Verbindungen.':'Noch keine Verbindungen. Lege sie unter Einstellungen → Integrationen an.'}</p>}
 </>}
 {mode==='manual'&&ids.length>=8&&<p className="hint">Bis zu acht Profile gezielt auswählen. „Alle automatisch“ verwendet alle aktivierten Verbindungen.</p>}
 {mode==='manual'&&ids.some(id=>!rows.some(row=>row.id===id))&&<p className="hint">Eine gespeicherte Verbindung ist nicht mehr verfügbar. Du kannst die Auswahl leeren.</p>}
 {(mode==='manual'||changed)&&<div className="binding-footer">{mode==='manual'&&<button type="button" disabled={disabled||busy||!saved} onClick={()=>{setIds([]);setMode('off')}}>Auswahl leeren</button>}<button type="button" className="primary" disabled={disabled||busy||!changed||!saved} onClick={()=>void save()}>{busy?'Wird gespeichert …':'Auswahl speichern'}</button></div>}
 </>}{error&&<p className="error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}</details>;
}
