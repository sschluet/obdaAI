import {useEffect,useId,useState} from 'react';
import './project-model.css';
export type ProjectModelPolicy={provider_id?:string;model?:string};
export type ProjectModelStatus={available:boolean;reason:string};
type Provider={id:string;name:string;kind:string;enabled:boolean;model:string;capabilities:string[]};
type API=(path:string,method?:string,body?:unknown)=>Promise<any>;
export function ProjectModelSelector({api,value,onChange,disabled=false,status}:{api:API;value:ProjectModelPolicy;onChange:(value:ProjectModelPolicy)=>void;disabled?:boolean;status?:ProjectModelStatus}){
 const id=useId();
 const [providers,setProviders]=useState<Provider[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState('');
 useEffect(()=>{let alive=true;api('/providers').then(catalog=>{if(alive)setProviders(catalog.providers)}).catch(()=>{if(alive)setError('Die Modellauswahl konnte nicht geladen werden. Eine gespeicherte Auswahl bleibt erhalten.')}).finally(()=>{if(alive)setLoading(false)});return()=>{alive=false}},[api]);
 const options=providers.filter(row=>row.enabled&&row.model&&row.capabilities.includes('text'));
 const eligible=(row:Provider)=>row.kind!=='local'||row.capabilities.includes('structured');
 const fixed=!!value.provider_id,selected=providers.find(row=>row.id===value.provider_id&&row.model===value.model);
 const savedMissing=fixed&&!options.some(row=>row.id===value.provider_id&&row.model===value.model);
 const key=fixed?JSON.stringify({provider_id:value.provider_id,model:value.model}):'auto';
 const reason=selected&&!eligible(selected)?'Das lokale Projektmodell benötigt strukturierte Ausgabe. Bitte eine geeignete Verbindung wählen.':!fixed?'Die normale automatische Modellauswahl gilt für dieses Projekt.':selected?.kind&&selected.kind!=='local'?'Cloud gewählt; Projektinhalte sind noch nicht für externe Modelle freigegeben.':savedMissing?'Das gespeicherte Modell ist derzeit nicht als aktive Textverbindung verfügbar. Es wird kein anderes Modell stillschweigend verwendet.':status?.reason||'Dieses Modell gilt für die Gespräche und Aufgaben des Projekts.';
 return <div className="project-model-setting"><label htmlFor={id}>Modell für dieses Projekt</label><select id={id} disabled={disabled||loading||!!error} value={key} onChange={event=>onChange(event.target.value==='auto'?{}:JSON.parse(event.target.value))}><option value="auto">Auto · automatisch auswählen</option>{options.map(row=><option key={row.id} disabled={!eligible(row)} value={JSON.stringify({provider_id:row.id,model:row.model})}>{row.name} · {row.model} · {row.kind==='local'?'Lokal':'Cloud'}{!eligible(row)?' · strukturierte Ausgabe fehlt':''}</option>)}{savedMissing&&<option value={key}>Gespeichert: {value.model||'Modell nicht verfügbar'} · derzeit nicht verfügbar</option>}</select><p className="hint">Gilt für Projektgespräche und zugehörige Aufgaben. Die Auswahl erteilt keine zusätzlichen Datenfreigaben oder Zugriffsrechte.</p>{loading?<p role="status">Konfigurierte Modelle werden geladen …</p>:error?<p role="status">{error}</p>:<p role="status">{reason}</p>}</div>;
}
