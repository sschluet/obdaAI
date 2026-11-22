import {checkGoogleDriveTransfers} from './google-drive-transfers';
import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {Check, FolderOpen, HardDrive, X} from 'lucide-react';
import type {IntegrationAPI} from './IntegrationRegistryPanel';
import './gmail-setup.css';
import './google-drive.css';

export type GoogleDriveSetupView = {
  available:boolean; integration_id:string|null; revision:number; name:string;
  client_id:string; client_secret_saved:boolean; configured:boolean; connected:boolean;
  account_email:string; redirect_uri:string; scopes:string[]; enabled:boolean;
  enable_source:boolean; enable_storage:boolean; source_folder_id:string;
  storage_folder_id:string; network_ready:boolean; message?:string;
};
export type GoogleDriveOpenRequest = {id?:string; key:number; folderId?:string}|null;
type DriveFile = {id:string;name:string;mimeType:string};

export function GoogleDriveSetupPanel({api,openRequest,onClose,onConfigured}:{
  api:IntegrationAPI;openRequest:GoogleDriveOpenRequest;onClose:()=>void;onConfigured:()=>void;
}) {
  const [setup,setSetup]=useState<GoogleDriveSetupView|null>(null),[step,setStep]=useState(1);
  const [name,setName]=useState('Google Drive'),[clientId,setClientId]=useState(''),[secret,setSecret]=useState('');
  const [source,setSource]=useState(false),[storage,setStorage]=useState(false),[folder,setFolder]=useState('root'),[folderName,setFolderName]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [folderAttempted,setFolderAttempted]=useState(false),[transfers,setTransfers]=useState<any[]|null>(null);
  const [browse,setBrowse]=useState<{id:string;name:string}[]>([]),[files,setFiles]=useState<DriveFile[]>([]),[nextPage,setNextPage]=useState('');
  const lock=useRef(false),dialog=useRef<HTMLDivElement>(null),closeRef=useRef(()=>{});
  const refreshCallback=useRef(onConfigured);refreshCallback.current=onConfigured;
  const open=!!openRequest;
  function populate(view:GoogleDriveSetupView){setSetup(view);setName(view.name||'Google Drive');setClientId(view.client_id||'');setSecret('');setSource(view.enable_source);setStorage(view.enable_storage);setFolder(view.source_folder_id||'root');}
  useEffect(()=>{
    if(!openRequest){setSecret('');return;}
    let alive=true;setSetup(null);setError('');setNotice('');setSecret('');setBrowse([]);setFiles([]);setFolderName('');setNextPage('');setFolderAttempted(false);setTransfers(null);
    void api('/integrations/google-drive/setup'+(openRequest.id?'?integration_id='+encodeURIComponent(openRequest.id):'')).then((v:GoogleDriveSetupView)=>{if(alive){populate(v);if(openRequest.folderId)setFolder(openRequest.folderId);setStep(v.configured?3:1);}}).catch(e=>{if(alive)setError((e as Error).message);});
    return()=>{alive=false;};
  },[api,openRequest?.key]);
  function close(){if(lock.current)return;setSecret('');setError('');onClose();}
  closeRef.current=close;
  useEffect(()=>{
    if(!open)return;
    const previous=document.activeElement as HTMLElement|null;
    const shell=document.querySelector<HTMLElement>('.shell'),wasInert=shell?.inert;if(shell)shell.inert=true;
    const focus=requestAnimationFrame(()=>dialog.current?.focus());
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();closeRef.current();}
      if(event.key!=='Tab')return;
      const controls=Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,a[href],[tabindex="0"]')||[]).filter(e=>e.getClientRects().length>0&&!e.closest('fieldset:disabled'));
      const first=controls[0],last=controls.at(-1);
      if(!first){event.preventDefault();dialog.current?.focus();}
      else if(event.shiftKey&&(document.activeElement===first||!dialog.current?.contains(document.activeElement)||document.activeElement===dialog.current)){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&(document.activeElement===last||!dialog.current?.contains(document.activeElement))){event.preventDefault();first.focus();}
    };
    document.addEventListener('keydown',key);
    return()=>{cancelAnimationFrame(focus);document.removeEventListener('keydown',key);if(shell)shell.inert=!!wasInert;requestAnimationFrame(()=>{if(previous?.isConnected)previous.focus();else document.querySelector<HTMLButtonElement>('.integration-registry > .registry-heading button')?.focus();});};
  },[open]);
  useEffect(()=>{if(open)requestAnimationFrame(()=>dialog.current?.querySelector<HTMLElement>('[data-drive-heading]')?.focus());},[open,step]);
  async function perform(action:()=>Promise<void>){if(lock.current)return;lock.current=true;setBusy(true);setError('');setNotice('');try{await action();}catch(e){setError((e as Error).message);}finally{lock.current=false;setBusy(false);}}
  async function refresh(){if(!setup?.integration_id)return;const current=await api('/integrations/google-drive/setup?integration_id='+setup.integration_id);populate(current);if(current.source_folder_id===setup.source_folder_id)setFolder(folder);refreshCallback.current();}
  async function save(){if(!setup)return;await perform(async()=>{
    const view=await api('/integrations/google-drive/setup','POST',{integration_id:setup.integration_id,expected_revision:setup.integration_id?setup.revision:null,request_id:crypto.randomUUID(),name:name.trim(),client_id:clientId.trim(),client_secret:secret||null,enable_source:source,enable_storage:storage,source_folder_id:folder.trim()||'root'});
    populate(view);setFolderName('');setStep(3);refreshCallback.current();
  });setSecret('');}
  async function authorize(){if(!setup?.integration_id)return;await perform(async()=>{
    const result=await api('/integrations/google-drive/'+setup.integration_id+'/authorize','POST',{expected_revision:setup.revision,request_id:crypto.randomUUID()});
    const url=new URL(result.authorization_url);
    if(url.origin!=='https://accounts.google.com'||url.pathname!=='/o/oauth2/v2/auth'||url.username||url.password||url.hash)throw new Error('Die Google-Anmeldeadresse ist nicht gültig.');
    refreshCallback.current();window.location.assign(url.href);
  });}
  async function browseFolder(id:string,label:string,trail?:{id:string;name:string}[],pageToken=''){if(!setup?.integration_id)return;await perform(async()=>{
    const result=await api('/integrations/google-drive/'+setup.integration_id+'/files?parent_id='+encodeURIComponent(id)+(pageToken?'&page_token='+encodeURIComponent(pageToken):''));
    setFiles(previous=>pageToken?[...previous,...(result.files||[])]:result.files||[]);setNextPage(result.next_page_token||'');setBrowse(trail||[...browse,{id,name:label}]);
  });}
  async function connectSource(){if(!setup?.integration_id)return;await perform(async()=>{
    const selectedFolder=folder.trim()||'root';
    const result=await api('/integrations/google-drive/'+setup.integration_id+'/source','POST',{expected_revision:setup.revision,folder_id:selectedFolder,max_files:50});
    await api('/knowledge-sources/'+result.connection_id+'/index','POST',{revision:result.revision,enabled:true});
    await refresh();setFolder(selectedFolder);setNotice('Die Drive-Quelle wird lokal eingelesen. Du findest sie unter Wissen → Wissensquellen.');
  });}
  async function createStorage(){if(!setup?.integration_id||folderAttempted)return;await perform(async()=>{
    setFolderAttempted(true);
    const result=await api('/integrations/google-drive/'+setup.integration_id+'/storage-folder','POST',{expected_revision:setup.revision,request_id:crypto.randomUUID()});
    await refresh();
    if(result.status!=='succeeded')throw new Error('Der Ablageordner ist noch nicht bestätigt. Bitte den gespeicherten Vorgang prüfen, bevor du es erneut versuchst.');
    setNotice('Der eigene obdaAI-Ablageordner ist bereit. Erstellte Dateien kannst du dort einzeln speichern.');
  });}
  async function refreshTransfers(){if(!setup?.integration_id)return;const integrationId=setup.integration_id;await perform(async()=>{const result=await checkGoogleDriveTransfers(api,integrationId);setTransfers(result.transfers);populate(result.setup);if(result.setup.source_folder_id===setup.source_folder_id)setFolder(folder);refreshCallback.current();});}
  async function disconnect(){if(!setup?.integration_id)return;await perform(async()=>{
    populate(await api('/integrations/google-drive/'+setup.integration_id+'/disconnect','POST',{expected_revision:setup.revision,revoke_google:false}));refreshCallback.current();setNotice('Drive ist in obdaAI getrennt. Deine Dateien bleiben erhalten.');
  });}
  if(!open)return null;
  const keepSecret=setup?.client_secret_saved&&clientId.trim()===setup.client_id;
  return createPortal(<div className="modal registry-overlay gmail-wizard-overlay"><div className="registry-dialog gmail-wizard drive-wizard" role="dialog" aria-modal="true" aria-labelledby="drive-wizard-title" ref={dialog} tabIndex={-1}>
    <div className="registry-heading"><div><h2 id="drive-wizard-title"><HardDrive size={21}/>Google Drive einrichten</h2><p>Optional als Wissensquelle und Ablage für fertige Dateien.</p></div><button type="button" aria-label="Google-Drive-Einrichtung schließen" disabled={busy} onClick={close}><X size={19}/></button></div>
    {error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {!setup?error?<button type="button" onClick={close}>Schließen</button>:<p role="status">Drive-Einrichtung wird geladen …</p>:!setup.available?<p>Für diese optionale Verbindung muss zuerst die verschlüsselte Zugangsdatenablage des Servers eingerichtet sein.</p>:<>
      <ol className="gmail-wizard-steps" aria-label="Google-Drive-Einrichtungsschritte">{['Vorbereiten','Zugang und Nutzung','Verbinden'].map((label,index)=><li key={label} aria-current={step===index+1?'step':undefined}><span>{index+1}</span>{label}</li>)}</ol>
      {step===1&&<section className="gmail-wizard-step"><h3 data-drive-heading tabIndex={-1}>1. Google vorbereiten</h3><p>Du benötigst einmalig einen OAuth-Webclient für diese private obdaAI-Installation. Dein Google-Passwort gibst du ausschließlich bei Google ein.</p><ol><li><a href="https://console.cloud.google.com/apis/library/drive.googleapis.com" target="_blank" rel="noopener noreferrer">Google Drive API aktivieren</a>.</li><li>Unter Google Auth Platform dein Konto als Testnutzer eintragen, sofern du den Testmodus verwendest.</li><li><a href="https://console.cloud.google.com/auth/clients" target="_blank" rel="noopener noreferrer">OAuth-Client als Webanwendung erstellen</a> und diese Weiterleitungsadresse exakt übernehmen:</li></ol><label>Autorisierte Weiterleitungs-URI<input readOnly value={setup.redirect_uri} onFocus={e=>e.currentTarget.select()}/></label><p>Client-ID und Client-Secret findest du anschließend im OAuth-Webclient.</p><div className="dialog-actions"><button type="button" onClick={close}>Abbrechen</button><button type="button" className="primary" onClick={()=>setStep(2)}>Weiter zu Zugang und Nutzung</button></div></section>}
      {step===2&&<form className="gmail-wizard-step" onSubmit={e=>{e.preventDefault();void save();}}><h3 data-drive-heading tabIndex={-1}>2. Zugang und Nutzung wählen</h3><fieldset disabled={busy}><label>Name der Verbindung<input required maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label><label>Google-Client-ID<input required maxLength={256} autoComplete="off" value={clientId} onChange={e=>setClientId(e.target.value)}/></label><label>Google-Client-Secret<input type="password" required={!keepSecret} autoComplete="new-password" maxLength={4096} value={secret} onChange={e=>setSecret(e.target.value)} placeholder={keepSecret?'Leer lassen: gespeicherten Zugang behalten':'Client-Secret aus Google Cloud'}/></label><div className="drive-usage-options"><label className="gmail-read-choice"><input type="checkbox" checked={source} onChange={e=>setSource(e.target.checked)}/><span><b>Als Wissensquelle verwenden</b><small>Dateien aus dem gewählten Ordner lesen und lokal durchsuchbar machen. Drive erhält die nötigen Dateianfragen; Inhalte bleiben für KI-Antworten lokal geschützt.</small></span></label><label className="gmail-read-choice"><input type="checkbox" checked={storage} onChange={e=>setStorage(e.target.checked)}/><span><b>Als Ablage verwenden</b><small>Fertige Dateien nach deiner ausdrücklichen Auswahl in einem eigenen obdaAI-Ordner speichern. Bestehende Drive-Dateien werden nicht überschrieben.</small></span></label></div>{source&&<details><summary>Quellordner einschränken (optional)</summary><label>Quellordner-ID<input required maxLength={200} value={folder} onChange={e=>{setFolder(e.target.value);setFolderName('');}} placeholder="root für Meine Ablage"/><small>„root“ liest Meine Ablage; alternativ die Ordner-ID aus der Drive-Adresse. Nach dem Verbinden kannst du den Ordner bequem auswählen.</small></label></details>}<p>Die Zugangsdaten werden verschlüsselt gespeichert. Diese Verbindung gibt keine Inhalte an externe KI-Modelle frei.</p>{setup.connected&&<p>Geänderte Zugriffsrechte erfordern eine erneute Anmeldung bei Google.</p>}<div className="dialog-actions"><button type="button" onClick={()=>setStep(1)}>Zurück</button><button type="submit" className="primary" disabled={!source&&!storage}>Zugang speichern und weiter</button></div></fieldset></form>}
      {step===3&&<section className="gmail-wizard-step"><h3 data-drive-heading tabIndex={-1}>{setup.connected?'Drive ist verbunden':'3. Mit Google verbinden'}</h3>{setup.connected?<p className="gmail-wizard-success" role="status"><Check size={20}/>Verbunden{setup.account_email?' · '+setup.account_email:''}</p>:<p>Melde dich bei Google an und bestätige die ausgewählten Rechte. Anschließend kehrst du hierher zurück.</p>}<ul className="drive-rights">{setup.enable_source&&<li>Quellen: lesender Zugriff auf Drive-Dateien; importiert wird nur der gewählte Ordner.</li>}{setup.enable_storage&&<li>Ablage: Zugriff auf Dateien, die obdaAI selbst anlegt.</li>}</ul>{!setup.network_ready&&<p role="status">Die Serverfreigabe für Google fehlt noch. Bitte zuerst die Netzwerkfreigabe prüfen lassen.</p>}<div className="dialog-actions"><button type="button" disabled={busy} onClick={()=>setStep(2)}>Zugang und Nutzung bearbeiten</button><button type="button" className="primary" disabled={busy||!setup.configured||!setup.network_ready} onClick={()=>void authorize()}>{setup.connected?'Erneut mit Google verbinden':'Mit Google verbinden'}</button></div>
        {setup.connected&&setup.enabled&&setup.enable_source&&<div className="setting-card drive-purpose"><h4><FolderOpen size={18}/>Wissensquelle</h4><p><b>Ausgewählter Ordner:</b> {folder==='root'?'Meine Ablage':folderName||'Gewählter Drive-Ordner'}</p><details><summary>Ordner-ID manuell angeben</summary><label>Quellordner-ID<input value={folder} maxLength={200} onChange={e=>{setFolder(e.target.value);setFolderName('');}} disabled={busy}/></label></details><button type="button" disabled={busy} onClick={()=>void browseFolder(folder.trim()||setup.source_folder_id||'root','Quellordner',[{id:folder.trim()||setup.source_folder_id||'root',name:'Quellordner'}])}>Ordner durchsuchen</button>{browse.length>0&&<div className="drive-folder-browser" aria-label="Drive-Ordner auswählen"><nav aria-label="Ordnerpfad">{browse.map((part,index)=><button type="button" key={part.id} disabled={busy} onClick={()=>void browseFolder(part.id,part.name,browse.slice(0,index+1))}>{part.name}</button>)}</nav><ul>{files.filter(file=>file.mimeType==='application/vnd.google-apps.folder').map(file=><li key={file.id}><button type="button" disabled={busy} onClick={()=>void browseFolder(file.id,file.name)}><FolderOpen size={16}/>{file.name}</button></li>)}</ul>{nextPage&&<button type="button" disabled={busy} onClick={()=>void browseFolder(browse.at(-1)!.id,browse.at(-1)!.name,browse,nextPage)}>Weitere Einträge laden</button>}{!files.some(file=>file.mimeType==='application/vnd.google-apps.folder')&&<p>Keine weiteren Unterordner in dieser Auswahl.</p>}<button type="button" disabled={busy} onClick={()=>{setFolder(browse.at(-1)!.id);setFolderName(browse.at(-1)!.name);setBrowse([]);setFiles([]);}}>Diesen Ordner verwenden</button></div>}<p>Bis zu 50 unterstützte Dokumente pro Abgleich werden als lokale Momentaufnahme eingelesen. Google-Dokumente werden in ein lesbares Dateiformat exportiert.</p><button type="button" className="primary" disabled={busy||!folder.trim()} onClick={()=>void connectSource()}>Ordner als Wissensquelle einlesen</button></div>}
        {setup.connected&&setup.enabled&&setup.enable_storage&&<div className="setting-card drive-purpose"><h4><HardDrive size={18}/>Dateiablage</h4>{setup.storage_folder_id?<p>Dein eigener obdaAI-Ordner ist bereit. Bei einer fertigen Datei wählst du „In Google Drive speichern“ und bestätigst die konkrete Übertragung.</p>:<><p>Erstelle einen eigenen obdaAI-Ordner in Meine Ablage. Erst danach können Dateien dort gespeichert werden.</p><button type="button" disabled={busy||folderAttempted} onClick={()=>void createStorage()}>obdaAI-Ablageordner erstellen</button>{folderAttempted&&!setup.storage_folder_id&&<p role="status">Ein Ablagevorgang wurde gestartet. Sein Ergebnis muss erst bestätigt werden; nicht erneut senden.</p>}</>}<button type="button" disabled={busy} onClick={()=>void refreshTransfers()}>Übertragungsstatus aktualisieren</button>{transfers&&<div className="drive-transfer-history" role="region" aria-label="Drive-Übertragungen">{!transfers.length?<p>Noch keine Übertragungen.</p>:transfers.map((transfer,index)=><p key={transfer.id||index}><b>{transfer.name||'obdaAI-Ablageordner'}</b> · {({succeeded:'Bestätigt',uncertain:'Unklar · nicht erneut senden',preparing:'Wird vorbereitet',dispatching:'Wird geprüft',failed:'Fehlgeschlagen'} as Record<string,string>)[transfer.status]||'Status prüfen'}{transfer.artifact_revision?' · Version '+transfer.artifact_revision:''}</p>)}</div>}</div>}
        {setup.connected&&<details className="gmail-disconnect"><summary>Verbindung trennen</summary><p>Entfernt den gespeicherten Drive-Zugriff in obdaAI. Dateien und lokale Momentaufnahmen bleiben erhalten. Google-Freigaben verwaltest du zusätzlich in deinem <a href="https://myaccount.google.com/connections" target="_blank" rel="noopener noreferrer">Google-Konto</a>.</p><button type="button" disabled={busy} onClick={()=>void disconnect()}>Drive-Zugriff in obdaAI trennen</button></details>}<div className="dialog-actions"><button type="button" disabled={busy} onClick={close}>Schließen</button></div>
      </section>}
    </>}
  </div></div>,document.body);
}
