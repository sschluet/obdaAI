import {useEffect,useRef,useState} from 'react';

type API=(path:string,method?:string,body?:unknown)=>Promise<any>;
type Field='language'|'length'|'tone'|'structure';
type Values=Partial<Record<Field,string>>;
type State={revision:number;overrides:Values;effective:Record<Field,string>;origins:Record<Field,{scope:string;revision:number}>};
const fields:{key:Field;label:string;options:[string,string][]}[]=[
 {key:'language',label:'Antwortsprache',options:[['auto','Sprache der Anfrage'],['de','Deutsch'],['en','Englisch']]},
 {key:'length',label:'Antwortlänge',options:[['balanced','Ausgewogen'],['short','Kurz'],['detailed','Ausführlich']]},
 {key:'tone',label:'Ton',options:[['neutral','Neutral'],['professional','Professionell'],['friendly','Freundlich']]},
 {key:'structure',label:'Gliederung',options:[['auto','Passend zum Inhalt'],['paragraphs','Fließtext bevorzugen'],['bullets','Aufzählungen bevorzugen']]},
];
const scopes:Record<string,string>={default:'App-Standard',global:'Persönliche Vorgaben',project:'Projekt',conversation:'Gespräch'};
export function PreferencesPanel({api,projectId,conversationId}:{api:API;projectId?:string|null;conversationId?:string|null}){
 const path=conversationId?'/preferences/conversations/'+conversationId:projectId?'/preferences/projects/'+projectId:'/preferences/global';
 const generation=useRef(0);
 const [data,setData]=useState<State|null>(null),[draft,setDraft]=useState<Values>({}),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 useEffect(()=>{let current=true;generation.current+=1;setBusy(false);setData(null);setDraft({});setError('');setNotice('');api(path).then((value:State)=>{if(current){setData(value);setDraft(value.overrides)}}).catch(()=>{if(current)setError('Antwortvorgaben konnten nicht geladen werden.')});return()=>{current=false}},[path,api]);
 async function save(values:Values){if(!data||busy)return;const requestGeneration=generation.current;setBusy(true);setError('');setNotice('');try{const result=await api(path,'PUT',{expected_revision:data.revision,overrides:values});if(requestGeneration!==generation.current)return;setData(result);setDraft(result.overrides);setNotice('Gespeichert. Gilt für neue Antworten; laufende Antworten behalten ihre Vorgaben.')}catch(e){if(requestGeneration===generation.current)setError(e instanceof Error?e.message:'Speichern fehlgeschlagen. Bitte neu laden.')}finally{if(requestGeneration===generation.current)setBusy(false)}}
 const dirty=data&&fields.some(field=>draft[field.key]!==data.overrides[field.key]);
 return <section className="setting-card response-preferences" aria-label="Antwortvorgaben"><h2>{conversationId?'Antwortvorgaben für dieses Gespräch':projectId?'Antwortvorgaben für dieses Projekt':'Persönliche Antwortvorgaben'}</h2><p className="hint">Persönliche Vorgaben → Projekt → Gespräch. Einzelne Einstellungen übernehmen den jeweiligen übergeordneten Wert. Gilt für neue Chatantworten; Dateien und Aufgaben verwenden ihre eigenen Vorlagen.</p>
 {data&&<><div className="preference-fields">{fields.map(field=>{const origin=data.origins[field.key];const current=field.options.find(([key])=>key===data.effective[field.key])?.[1];return <label key={field.key}>{field.label}<select aria-label={field.label} value={draft[field.key]??''} disabled={busy} onChange={event=>setDraft(value=>{const next={...value};if(event.target.value)next[field.key]=event.target.value;else delete next[field.key];return next})}><option value="">Übernehmen</option>{field.options.map(([value,label])=><option value={value} key={value}>{label}</option>)}</select><small className="hint">Gespeichert wirksam: {current} · {scopes[origin.scope]??origin.scope}{origin.revision>0?' · Version '+origin.revision:''}</small></label>})}</div><div className="button-row"><button disabled={busy||!dirty} onClick={()=>void save(draft)}>{busy?'Speichert …':'Vorgaben speichern'}</button><button disabled={busy||Object.keys(data.overrides).length===0} onClick={()=>void save({})}>Alle Vorgaben übernehmen</button><button disabled={busy} onClick={()=>{setError('');const requestGeneration=generation.current;api(path).then((value:State)=>{if(requestGeneration!==generation.current)return;setData(value);setDraft(value.overrides);setNotice('Aktuelle Vorgaben geladen.')}).catch(()=>{if(requestGeneration===generation.current)setError('Neu laden fehlgeschlagen.')})}}>Neu laden</button></div></>}
 {!data&&!error&&<p role="status">Antwortvorgaben werden geladen …</p>}{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}<p className="hint">Diese Einstellungen ändern keine Modellwahl, Cloudfreigabe, Websuche oder Schreibrechte. Einstellungen werden am Server gespeichert.</p></section>;
}
