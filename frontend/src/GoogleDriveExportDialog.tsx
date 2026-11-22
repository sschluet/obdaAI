import {checkGoogleDriveTransfers} from './google-drive-transfers';
import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {HardDrive,X} from 'lucide-react';
import type {IntegrationAPI,IntegrationRow} from './IntegrationRegistryPanel';
import './google-drive.css';

type ReadyFile={artifact_id:string;revision:number;title:string;kind:string};
export function GoogleDriveExportDialog({api,file,onClose}:{api:IntegrationAPI;file:ReadyFile;onClose:()=>void}){
  const [targets,setTargets]=useState<IntegrationRow[]>([]),[targetId,setTargetId]=useState('');
  const [loading,setLoading]=useState(true),[approved,setApproved]=useState(false),[busy,setBusy]=useState(false),[attempted,setAttempted]=useState(false);
  const [error,setError]=useState(''),[result,setResult]=useState<any|null>(null);
  const dialog=useRef<HTMLDivElement>(null),lock=useRef(false),request=useRef(crypto.randomUUID()),closeRef=useRef(()=>{});
  function close(){if(!lock.current)onClose();}closeRef.current=close;
  useEffect(()=>{let alive=true;void api('/integrations').then(value=>{
    if(!alive)return;
    const list=(value.integrations as IntegrationRow[]).filter(row=>row.kind==='google_drive'&&row.enabled&&row.writes_enabled&&row.availability_reason==='ready'&&row.config.connected&&row.config.enable_storage&&row.config.storage_folder_id);
    setTargets(list);setTargetId(list[0]?.id||'');
  }).catch(e=>{if(alive)setError((e as Error).message);}).finally(()=>{if(alive)setLoading(false);});return()=>{alive=false;};},[api]);
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null,shell=document.querySelector<HTMLElement>('.shell'),wasInert=shell?.inert;if(shell)shell.inert=true;
    dialog.current?.focus();
    const key=(e:KeyboardEvent)=>{
      if(e.key==='Escape'){e.preventDefault();closeRef.current();}
      if(e.key!=='Tab')return;
      const controls=Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href]')||[]);
      const first=controls[0],last=controls.at(-1);
      if(!first){e.preventDefault();dialog.current?.focus();}
      else if(e.shiftKey&&(document.activeElement===first||!dialog.current?.contains(document.activeElement)||document.activeElement===dialog.current)){e.preventDefault();last?.focus();}
      else if(!e.shiftKey&&(document.activeElement===last||!dialog.current?.contains(document.activeElement))){e.preventDefault();first.focus();}
    };document.addEventListener('keydown',key);
    return()=>{document.removeEventListener('keydown',key);if(shell)shell.inert=!!wasInert;requestAnimationFrame(()=>{if(previous?.isConnected)previous.focus();});};
  },[]);
  const target=targets.find(row=>row.id===targetId);
  async function checkStatus(){
    if(!target||!attempted||lock.current)return;lock.current=true;setBusy(true);setError('');
    try{const checked=await checkGoogleDriveTransfers(api,target.id,request.current);const own=checked.transfers.find(row=>row.request_id===request.current&&row.artifact_id===file.artifact_id&&row.artifact_revision===file.revision);if(own)setResult(own);else setError('Kein bestätigter Übertragungsvorgang gefunden. Bitte nicht erneut senden.');}
    catch(e){setError((e as Error).message+' Der Status ist weiterhin nicht bestätigt.');}
    finally{lock.current=false;setBusy(false);}
  }
  async function save(){
    if(!target||!approved||attempted||lock.current)return;
    lock.current=true;setBusy(true);setAttempted(true);setError('');
    try{setResult(await api('/integrations/google-drive/'+target.id+'/export','POST',{
      expected_revision:target.revision,request_id:request.current,artifact_id:file.artifact_id,artifact_revision:file.revision,cloud_upload_approved:true,
    }));}catch(e){setError((e as Error).message+' Der Übertragungsstatus ist nicht bestätigt. Bitte den gespeicherten Vorgang prüfen; nicht erneut senden.');}
    finally{lock.current=false;setBusy(false);}
  }
  return createPortal(<div className="modal registry-overlay"><div className="registry-dialog drive-export-dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="drive-export-title" tabIndex={-1}>
    <div className="registry-heading"><h2 id="drive-export-title"><HardDrive size={20}/>In Google Drive speichern</h2><button type="button" aria-label="Drive-Übertragung schließen" disabled={busy} onClick={close}><X size={18}/></button></div>
    {error&&<p className="error" role="alert">{error}</p>}
    {loading?<p role="status">Verfügbare Drive-Ablagen werden geladen …</p>:!targets.length?<p>Es ist noch keine aktive Drive-Ablage eingerichtet. Verbinde Google Drive unter Einstellungen → Integrationen, aktiviere „Als Ablage verwenden“ und erstelle den obdaAI-Ablageordner.</p>:<>
      <dl><dt>Datei</dt><dd>{file.title} · {file.kind.toUpperCase()}</dd><dt>Version</dt><dd>{file.revision}</dd></dl>
      <label>Google-Drive-Verbindung<select disabled={busy||attempted} value={targetId} onChange={e=>{setTargetId(e.target.value);setApproved(false);}}>{targets.map(row=><option key={row.id} value={row.id}>{row.name}{row.config.account_email?' · '+row.config.account_email:''}</option>)}</select></label>
      {target&&<p>Ziel: eigener obdaAI-Ordner{target.config.account_email?' im Konto '+target.config.account_email:''}. Die Datei wird als neue Datei gespeichert; vorhandene Dateien bleiben erhalten.</p>}
      {!attempted&&<label className="drive-transfer-choice"><input type="checkbox" checked={approved} onChange={e=>setApproved(e.target.checked)}/><span>Diese konkrete Dateiversion an mein Google Drive übertragen. Die Datei kann private Inhalte enthalten. Dies gibt keine Inhalte für externe KI-Modelle frei.</span></label>}
      {result&&<p role="status">{result.status==='succeeded'?'Die Datei wurde in Google Drive gespeichert.':'Die Übertragung ist noch nicht bestätigt. Bitte den gespeicherten Vorgang prüfen; nicht erneut senden.'}</p>}
      {attempted&&result?.status!=='succeeded'&&<button type="button" disabled={busy} onClick={()=>void checkStatus()}>Übertragungsstatus prüfen</button>}
      <div className="dialog-actions"><button type="button" disabled={busy} onClick={close}>Schließen</button><button type="button" className="primary" disabled={busy||!approved||!target||attempted} onClick={()=>void save()}>{busy?'Datei wird übertragen …':result?.status==='succeeded'?'Gespeichert':'Diese Version in Drive speichern'}</button></div>
    </>}
  </div></div>,document.body);
}
