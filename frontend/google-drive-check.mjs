// Real React and fixture APIs; only Google-specific transport/setup responses are synthetic.
// This does not establish real Google OAuth, Drive upload, or server egress acceptance.
import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
import {spawn} from 'node:child_process';
import {mkdtemp,realpath,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:net';
const base='http://127.0.0.1:18767',pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let server,serverExit,folder,serverLog='',startError;
const stop=()=>{if(server?.pid&&server.exitCode===null&&!server.signalCode)server.kill('SIGTERM')};
const interrupt=()=>{stop();process.exit(130)},terminate=()=>{stop();process.exit(143)};
try{
 await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',error=>reject(Error('Drive fixture port18767 unavailable ('+error.code+'); existing service untouched')));probe.listen(18767,'127.0.0.1',()=>probe.close(resolve));});
 folder=await realpath(await mkdtemp(join(tmpdir(),'obdaai-drive-ui-')));
 const root=fileURLToPath(new URL('../',import.meta.url));
 const python=process.env.HUB_TEST_PYTHON?resolve(process.env.HUB_TEST_PYTHON):fileURLToPath(new URL('../.venv/bin/python',import.meta.url));
 server=spawn(python,['-m','uvicorn','scripts.browser_fixture:app','--host','127.0.0.1','--port','18767'],{cwd:root,env:{...process.env,HUB_BROWSER_FIXTURE_DIR:folder,HUB_BROWSER_ORIGIN:base},stdio:['ignore','pipe','pipe']});
 serverExit=new Promise(resolve=>server.once('close',resolve));server.once('error',e=>{startError=e;});
 for(const stream of [server.stdout,server.stderr])stream.on('data',chunk=>{serverLog=(serverLog+chunk.toString()).slice(-6000);});
 process.once('exit',stop);process.once('SIGINT',interrupt);process.once('SIGTERM',terminate);
 const deadline=Date.now()+30000;let healthy=false;
 while(Date.now()<deadline){if(startError)throw startError;if(server.exitCode!==null||server.signalCode)throw Error('Owned fixture stopped: '+serverLog);try{healthy=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok;}catch{}if(healthy)break;await pause(100);}
 if(!healthy)throw Error('Owned Drive fixture startup timed out: '+serverLog);
 await checks();
}finally{
 if(server){stop();let timer;try{await Promise.race([serverExit,new Promise(resolve=>{timer=setTimeout(resolve,5000);})]);}finally{clearTimeout(timer);}if(server.pid&&server.exitCode===null&&!server.signalCode){server.kill('SIGKILL');await serverExit;}}
 process.removeListener('exit',stop);process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',terminate);
 if(folder)await rm(folder,{recursive:true,force:true});
}
async function checks(){
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1280,height:950}}),errors=[];
 page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
 const id='8a4af176-2d8a-4d7b-9f6b-3322dc37b829',connection='53b03bd5-a5d8-4d39-ae0e-7ca93ce1111f';
 let sourceInfo=null,sourceCalls=0,indexCalls=0,folderCalls=0,exportCalls=[],uncertainExport=false,driveTransfers=[],reconcileCalls=0;
 let view={available:true,integration_id:null,revision:0,name:'Google Drive',client_id:'',client_secret_saved:false,configured:false,connected:false,account_email:'',redirect_uri:base+'/api/integrations/google-drive/callback',scopes:[],enabled:false,enable_source:false,enable_storage:false,source_folder_id:'root',storage_folder_id:'',network_ready:true};
 const row=()=>({id,name:view.name,kind:'google_drive',revision:view.revision,enabled:view.enabled,writes_enabled:view.connected&&view.enable_storage,secret_saved:true,target_approved:true,execution_available:false,availability_reason:!view.enabled?'disabled':view.connected?'ready':'credential_missing',check_available:false,config:{url:'https://www.googleapis.com/drive/v3',auth:'oauth',connected:view.connected,account_email:view.account_email,enable_source:view.enable_source,enable_storage:view.enable_storage,storage_folder_id:view.storage_folder_id}});
 try{
  await page.route(base+'/api/**',async route=>{
   const request=route.request(),url=new URL(request.url()),path=url.pathname,method=request.method();
   const json=body=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
   if(path==='/api/integrations'&&method==='GET'){
    const response=await route.fetch(),original=await response.json();return json({...original,integrations:[...original.integrations,...(view.integration_id?[row()]:[])]});
   }
   if(path==='/api/knowledge-sources'&&method==='GET'){
    const response=await route.fetch(),original=await response.json();return json([...original,...(sourceInfo?[sourceInfo]:[])]);
   }
   if(path==='/api/integrations/google-drive/setup'){
    if(method==='GET')return json(view);
    const data=request.postDataJSON();if(!data.enable_source||!data.enable_storage||!data.request_id)throw Error('Usage choice/request identity missing');
    view={...view,integration_id:id,revision:1,name:data.name,client_id:data.client_id,client_secret_saved:true,configured:true,enable_source:data.enable_source,enable_storage:data.enable_storage,source_folder_id:data.source_folder_id};return json(view);
   }
   if(path===`/api/integrations/google-drive/${id}/authorize`)return json({authorization_url:'https://example.invalid/not-google',revision:view.revision});
   if(path===`/api/integrations/google-drive/${id}/files`)return json({files:[{id:'SyntheticFolder',name:'Synthetic source documents',mimeType:'application/vnd.google-apps.folder'},{id:'SyntheticFile',name:'Synthetic source.md',mimeType:'text/markdown'}],next_page_token:''});
   if(path===`/api/integrations/google-drive/${id}/source`){
    sourceCalls++;const data=request.postDataJSON();if(data.folder_id!=='SyntheticFolder'||data.expected_revision!==view.revision)throw Error('Source folder/revision not bound');
    sourceInfo={id:connection,connection_id:connection,name:'Synthetic Drive source',kind:'google_drive',address:'Google Drive',project_id:'979137bb-9f2d-4329-b651-31b378bafcc9',revision:1,status:'ready',enabled:true,indexed:1,pending:0,chat_ready:true,config:{integration_id:id}};return json(sourceInfo);
   }
   if(path===`/api/knowledge-sources/${connection}/index`){indexCalls++;return json(sourceInfo);}
   if(path===`/api/integrations/google-drive/${id}/storage-folder`){folderCalls++;view={...view,revision:view.revision+1,storage_folder_id:'SyntheticStorage'};return json({status:'succeeded',folder_id:'SyntheticStorage',integration_revision:view.revision});}
   if(path===`/api/integrations/google-drive/${id}/exports`&&method==='GET')return json(driveTransfers);
   if(path.startsWith(`/api/integrations/google-drive/${id}/exports/`)&&path.endsWith('/reconcile')){const transfer=driveTransfers.find(row=>row.id===path.split('/').at(-2));if(!transfer||request.postDataJSON().expected_revision!==view.revision||transfer.status!=='uncertain')throw Error('Unsafe or unbound reconciliation');reconcileCalls++;transfer.status='succeeded';return json(transfer);}
   if(path===`/api/integrations/google-drive/${id}/export`){const data=request.postDataJSON();exportCalls.push(data);const transfer={...data,id:crypto.randomUUID(),integration_revision:data.expected_revision,status:uncertainExport?'uncertain':'succeeded',remote_id:'SyntheticExport',name:'Synthetic Drive result.docx'};driveTransfers.unshift(transfer);return json(transfer);}
   return route.fallback();
  });
  await page.goto(base);await loginFixture(page);
  await page.getByRole('button',{name:'Einstellungen',exact:true}).click();await page.getByRole('button',{name:'Integrationen',exact:true}).click();
  await page.getByRole('button',{name:'Verbindung hinzufügen',exact:true}).click();await page.getByRole('button',{name:/Google Drive.*Wissensquelle/}).click();
  let wizard=page.getByRole('dialog',{name:'Google Drive einrichten',exact:true});await wizard.waitFor();
  await wizard.getByLabel('Autorisierte Weiterleitungs-URI',{exact:true}).waitFor();
  await wizard.getByRole('button',{name:'Weiter zu Zugang und Nutzung',exact:true}).click();
  if(await wizard.getByRole('checkbox',{name:/Als Wissensquelle verwenden/}).isChecked()||await wizard.getByRole('checkbox',{name:/Als Ablage verwenden/}).isChecked())throw Error('Optional usage was silently enabled');
  await wizard.getByLabel('Google-Client-ID',{exact:true}).fill('synthetic-client.apps.googleusercontent.com');await wizard.getByLabel('Google-Client-Secret',{exact:true}).fill('SYNTHETIC_ONLY_NOT_REAL');
  await wizard.getByRole('checkbox',{name:/Als Wissensquelle verwenden/}).check();await wizard.getByRole('checkbox',{name:/Als Ablage verwenden/}).check();
  await wizard.getByRole('button',{name:'Zugang speichern und weiter',exact:true}).click();await wizard.getByRole('button',{name:'Mit Google verbinden',exact:true}).click();await wizard.getByRole('alert').filter({hasText:'Google-Anmeldeadresse'}).waitFor();
  if(new URL(page.url()).origin!==base)throw Error('Untrusted authorization URL was followed');
  await wizard.getByRole('button',{name:'Google-Drive-Einrichtung schließen',exact:true}).click();
  view={...view,connected:true,enabled:true,account_email:'synthetic-drive@example.invalid'};
  await page.goto('about:blank');await page.goto(base+'/?view=Einstellungen&settingsTab=Integrationen#google_drive_result=connected&google_drive_integration='+id);
  // The synthetic callback resumes the existing dialog, not an unrelated agent-rules editor.
  wizard=page.getByRole('dialog',{name:'Google Drive einrichten',exact:true});await wizard.waitFor();
  await wizard.getByRole('button',{name:'Ordner durchsuchen',exact:true}).click();await wizard.getByRole('button',{name:'Synthetic source documents',exact:true}).click();await wizard.getByRole('button',{name:'Diesen Ordner verwenden',exact:true}).click();
  await wizard.getByRole('button',{name:'Ordner als Wissensquelle einlesen',exact:true}).click();await wizard.getByText('Die Drive-Quelle wird lokal eingelesen.',{exact:false}).waitFor();
  if(sourceCalls!==1||indexCalls!==1)throw Error('Explicit source setup did not start exactly one index');
  await wizard.getByRole('button',{name:'obdaAI-Ablageordner erstellen',exact:true}).click();await wizard.getByText('Der eigene obdaAI-Ablageordner ist bereit.',{exact:false}).waitFor();if(folderCalls!==1)throw Error('Duplicate folder request');if(await wizard.getByLabel('Quellordner-ID',{exact:true}).inputValue()!=='SyntheticFolder')throw Error('Storage setup silently widened the selected source folder');
  driveTransfers.push({id:crypto.randomUUID(),request_id:crypto.randomUUID(),integration_revision:view.revision,status:'dispatching',name:'Synthetic in-flight transfer'},{id:crypto.randomUUID(),request_id:crypto.randomUUID(),integration_revision:view.revision-1,status:'uncertain',name:'Synthetic stale transfer'});await wizard.getByRole('button',{name:'Übertragungsstatus aktualisieren',exact:true}).click();await wizard.getByRole('region',{name:'Drive-Übertragungen',exact:true}).or(wizard.getByLabel('Drive-Übertragungen',{exact:true})).first().waitFor();if(reconcileCalls)throw Error('In-flight or stale-rights transfer was reconciled');
  if(process.env.DRIVE_SCREENSHOT_PATH)await page.screenshot({path:process.env.DRIVE_SCREENSHOT_PATH,fullPage:true,animations:'disabled'});
  await page.setViewportSize({width:320,height:850});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)||await wizard.evaluate(node=>node.scrollWidth>node.clientWidth))throw Error('Drive wizard overflows mobile viewport');
  await page.keyboard.press('Escape');await wizard.waitFor({state:'hidden'});await page.setViewportSize({width:1280,height:950});
  await page.getByRole('button',{name:'Wissen',exact:true}).click();await page.getByRole('heading',{name:'Synthetic Drive source',exact:true}).waitFor();
  await page.getByRole('button',{name:'Projekte',exact:true}).click();await page.getByRole('button',{name:'Neues Projekt',exact:true}).click();
  await page.getByLabel('Projektname',{exact:true}).fill('Synthetic Drive artifact');await page.getByRole('button',{name:'Projektraum erstellen',exact:true}).click();await page.getByRole('tab',{name:'Erstellte Dateien',exact:true}).click();
  await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();let file=page.getByRole('dialog',{name:'Datei erstellen',exact:true});await file.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();await file.getByLabel('Dateititel',{exact:true}).fill('Synthetic Drive result');await file.getByLabel('Dokumenttext',{exact:true}).fill('Only invented UI acceptance content.');await file.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
  await page.getByRole('button',{name:'In Google Drive speichern',exact:true}).click();let transfer=page.getByRole('dialog',{name:'In Google Drive speichern',exact:true});
  await page.setViewportSize({width:320,height:850});if(await transfer.evaluate(node=>node.scrollWidth>node.clientWidth))throw Error('Drive transfer dialog overflows mobile viewport');await page.setViewportSize({width:1280,height:950});
  const send=transfer.getByRole('button',{name:'Diese Version in Drive speichern',exact:true});await send.waitFor();if(!await send.isDisabled()||exportCalls.length)throw Error('Drive transfer started without explicit per-file consent');
  await transfer.getByRole('checkbox',{name:/Diese konkrete Dateiversion/}).check();await send.click();await transfer.getByText('Die Datei wurde in Google Drive gespeichert.',{exact:true}).waitFor();
  if(exportCalls.length!==1||exportCalls[0].cloud_upload_approved!==true||exportCalls[0].artifact_revision!==1||exportCalls[0].expected_revision!==view.revision||!exportCalls[0].request_id)throw Error('Drive export not bound to selected file/revision/connection');
  if(!await transfer.getByRole('button',{name:'Gespeichert',exact:true}).isDisabled())throw Error('Completed transfer can accidentally submit again');
  await transfer.getByRole('button',{name:'Schließen',exact:true}).click();
  uncertainExport=true;await page.getByRole('button',{name:'In Google Drive speichern',exact:true}).click();transfer=page.getByRole('dialog',{name:'In Google Drive speichern',exact:true});await transfer.getByRole('checkbox',{name:/Diese konkrete Dateiversion/}).check();await transfer.getByRole('button',{name:'Diese Version in Drive speichern',exact:true}).click();await transfer.getByText('Die Übertragung ist noch nicht bestätigt.',{exact:false}).waitFor();if(exportCalls.length!==2||!await transfer.getByRole('button',{name:'Diese Version in Drive speichern',exact:true}).isDisabled())throw Error('Uncertain transfer can be blindly retried');await transfer.getByRole('button',{name:'Übertragungsstatus prüfen',exact:true}).click();await transfer.getByText('Die Datei wurde in Google Drive gespeichert.',{exact:true}).waitFor();if(reconcileCalls!==1||exportCalls.length!==2)throw Error('Status check did not reconcile exactly once without another upload');await page.keyboard.press('Escape');await transfer.waitFor({state:'hidden'});
  if(errors.length)throw Error(errors.join('\n'));
  console.log('Google Drive UI passed: optional guided setup, URL guard, callback resume, source folder/index, managed storage, existing knowledge navigation, actual fixture artifact and explicit single per-version cloud transfer, uncertain-result retry lock, explicit metadata-only reconciliation without another upload, in-flight/stale-grant exclusion, mobile and Escape. Google transport/OAuth mocked; no real account calls.');
 }finally{await browser.close();}
}
