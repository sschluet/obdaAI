// Real React/auth/conversation APIs on a fresh isolated synthetic fixture.
// Agent jobs and displayed messages are synthetic stubs; no live targets or model calls.
import './agent-job-state-check.mjs';
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,realpath,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:net';
const base='http://127.0.0.1:18831',pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let server,serverExit,folder,serverLog='',startError;
const stop=()=>{if(server?.pid&&server.exitCode===null&&!server.signalCode)server.kill('SIGTERM')};
const interrupt=()=>{stop();process.exit(130)},terminate=()=>{stop();process.exit(143)};
try{
 await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',error=>reject(Error('Agent activity fixture port18831 unavailable ('+error.code+'); existing service untouched')));probe.listen(18831,'127.0.0.1',()=>probe.close(resolve));});
 folder=await realpath(await mkdtemp(join(tmpdir(),'obdaai-agent-activity-')));
 const root=fileURLToPath(new URL('../',import.meta.url));
 const python=process.env.HUB_TEST_PYTHON?resolve(process.env.HUB_TEST_PYTHON):fileURLToPath(new URL('../.venv/bin/python',import.meta.url));
 server=spawn(python,['-m','uvicorn','scripts.browser_fixture:app','--host','127.0.0.1','--port','18831'],{cwd:root,env:{...process.env,HUB_BROWSER_FIXTURE_DIR:folder,HUB_BROWSER_ORIGIN:base},stdio:['ignore','pipe','pipe']});
 serverExit=new Promise(resolve=>server.once('close',resolve));server.once('error',e=>{startError=e;});
 for(const stream of [server.stdout,server.stderr])stream.on('data',chunk=>{serverLog=(serverLog+chunk.toString()).slice(-6000);});
 process.once('exit',stop);process.once('SIGINT',interrupt);process.once('SIGTERM',terminate);
 const deadline=Date.now()+30000;let healthy=false;
 while(Date.now()<deadline){if(startError)throw startError;if(server.exitCode!==null||server.signalCode)throw Error('Owned fixture stopped: '+serverLog);try{healthy=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok;}catch{}if(healthy)break;await pause(100);}
 if(!healthy)throw Error('Owned Agent activity fixture startup timed out: '+serverLog);
 await checks();
}finally{
 if(server){stop();let timer;try{await Promise.race([serverExit,new Promise(resolve=>{timer=setTimeout(resolve,5000);})]);}finally{clearTimeout(timer);}if(server.pid&&server.exitCode===null&&!server.signalCode){server.kill('SIGKILL');await serverExit;}}
 process.removeListener('exit',stop);process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',terminate);
 if(folder)await rm(folder,{recursive:true,force:true});
}
async function checks(){
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:320,height:740}}),errors=[];page.setDefaultTimeout(15000);page.on('pageerror',error=>errors.push(error.message));
 try{
 await page.goto(base);await page.getByLabel('Passwort',{exact:true}).fill('synthetic-ui-password');const logged=page.waitForResponse(r=>r.url()===base+'/api/login'&&r.request().method()==='POST');await page.getByRole('button',{name:'Anmelden',exact:true}).click();const auth=await(await logged).json(),headers={'X-CSRF-Token':auth.csrf,Origin:base};await page.getByRole('button',{name:'Navigation öffnen',exact:true}).waitFor();
 const response=await page.request.post(base+'/api/conversations',{headers,data:{}});if(!response.ok())throw Error('Synthetic activity chat create failed');const chat=await response.json();let cancelled=0,writeCalls=0,routePending=false,releaseRoute,created=0,pollUnavailable=false,unrelatedResponse=false,holdOldPoll=false,markOldPoll,releaseOldPoll;
 page.on('request',request=>{if(request.method()==='POST'&&/\/(messages|agent-runs)$/.test(new URL(request.url()).pathname))created++});
 let job={id:'00000000-0000-0000-0000-000000000101',created:50,status:'running',goal:'Prüfe die synthetischen Zustände.',summary:'',cancel_requested:false,steps:[],activity:{phase:'planning',message:'Der Auftrag wird lokal vorbereitet.',can_cancel:true,elapsed_seconds:8,completed_steps:0}};
 await page.route(base+'/api/integrations',route=>route.fulfill({json:{integrations:[{id:'00000000-0000-0000-0000-000000000201',name:'Aurora Home',kind:'home_assistant',enabled:true,writes_enabled:false,revision:1,execution_available:true}]}}));
 await page.route(base+'/api/integration-bindings/conversation/'+chat.id,route=>route.fulfill({json:{revision:1,selection_mode:'automatic',integration_ids:[],effective_selection_mode:'automatic',effective_integration_ids:['00000000-0000-0000-0000-000000000201'],execution_available:true}}));
 await page.route(base+'/api/agent-runs?*',async route=>{const captured=structuredClone(job);if(holdOldPoll){holdOldPoll=false;markOldPoll();await new Promise(resolve=>releaseOldPoll=resolve)}return pollUnavailable?route.fulfill({status:503,json:{detail:'Synthetischer Statusabruf nicht verfügbar'}}):route.fulfill({json:[captured]})});
 await page.route(base+'/api/agent-runs/'+job.id+'/cancel',async route=>{if(route.request().method()!=='POST')throw Error('Wrong cancellation method');cancelled++;job={...job,cancel_requested:true,activity:{...job.activity,can_cancel:false}};await route.fulfill({json:job})});
 await page.route(base+'/api/conversations/'+chat.id,async route=>{if(route.request().method()!=='GET'){writeCalls++;return route.abort()}const actual=await route.fetch();const detail=await actual.json();return route.fulfill({json:{...detail,title:'Aurora Beispiel',messages:[{id:'question',role:'user',content:job.goal,label:'LOCAL_ONLY',revision:1},...(['observed','succeeded','failed','unverified','uncertain','cancelled'].includes(job.status)?[{id:'synthetic-answer',role:'assistant',content:job.summary||'Die synthetische Abfrage ist abgeschlossen.',label:'LOCAL_ONLY',revision:1,processing:{...(unrelatedResponse?{}:{agent_job_id:job.id}),provider:'local',model_used:false,status:'succeeded'}}]:[])]}})});
 await page.route(base+'/api/conversations?*',async route=>{if(route.request().method()!=='GET')return route.continue();const response=await route.fetch();const rows=await response.json();const titled=rows.map(row=>row.id===chat.id?{...row,title:'Aurora Beispiel'}:row);if(!titled.some(row=>row.id===chat.id))titled.push({...chat,title:'Aurora Beispiel'});await route.fulfill({json:titled})});
 await page.goto(base+'/?chat='+chat.id);const activity=page.getByRole('region',{name:'Aktueller Auftrag',exact:true}),details=page.getByRole('region',{name:'Details Abarbeitung',exact:true}).locator('.agent-work-details');
 await activity.getByText('Der Auftrag wird lokal vorbereitet.',{exact:true}).waitFor();if(await page.getByRole('region',{name:'Gespräch',exact:true}).evaluate(e=>e.getBoundingClientRect().height)<230)throw Error('Mobile chrome leaves insufficient conversation space');if(await details.evaluate(e=>e.open))throw Error('Live activity auto-opened technical details');
 if(!await activity.getByRole('button',{name:'Abbrechen',exact:true}).isVisible())throw Error('Inline cancellation hidden');
 job={...job,activity:{phase:'reading',message:'Home Assistant wird gelesen.',completed_steps:2,can_cancel:true}};await activity.getByText('Home Assistant wird gelesen.',{exact:true}).waitFor();await activity.getByText('2 Schritte abgeschlossen',{exact:true}).waitFor();
 if(await details.evaluate(e=>e.open))throw Error('Reading progress expanded details');
 for(const width of [320,390,1440]){await page.setViewportSize({width,height:740});if(!await activity.isVisible()||await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Live activity unreachable/overflow at '+width)}
 await page.getByRole('button',{name:'Aurora Beispiel',exact:true}).waitFor();
 await mkdir(fileURLToPath(new URL('../.local/browser/',import.meta.url)),{recursive:true});
 await page.setViewportSize({width:390,height:844});
 // Resizing from desktop can leave the sidebar transition in its first frame.
 // Exercise real drawer controls, then require settled geometry and an unobscured
 // phase before capturing; visibility alone accepts off-canvas/covered elements.
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 await page.getByRole('button',{name:'Navigation schließen',exact:true}).click();
 await page.waitForFunction(()=>{const sidebar=document.querySelector('.sidebar');return sidebar&&!sidebar.classList.contains('open')&&sidebar.getBoundingClientRect().right<=1&&!document.querySelector('.scrim')});
 const liveMessage=activity.getByText('Home Assistant wird gelesen.',{exact:true});
 if(!await liveMessage.evaluate(el=>{const r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return !!hit&&(hit===el||el.contains(hit))}))throw Error('Mobile activity screenshot is obscured');
 await page.evaluate(()=>document.activeElement?.blur());
 await page.screenshot({animations:'disabled',path:fileURLToPath(new URL('../.local/browser/agent-activity-mobile.png',import.meta.url))});
 await page.setViewportSize({width:1440,height:900});
 await page.waitForFunction(()=>{const sidebar=document.querySelector('.sidebar');return sidebar&&Math.abs(sidebar.getBoundingClientRect().left)<=1});
 await page.screenshot({animations:'disabled',path:fileURLToPath(new URL('../.local/browser/agent-activity-desktop.png',import.meta.url))});await page.setViewportSize({width:320,height:740});
 // A backend-reported wait stays explicit; no invented percentage or thought text.
 job={...job,activity:{phase:'planning',message:'Der Auftrag wartet auf das lokale Modell.',waiting_reason:'Das lokale Modell bearbeitet gerade eine andere Anfrage.',next_action:'Du kannst warten oder abbrechen.',can_cancel:true}};await activity.getByText('Das lokale Modell bearbeitet gerade eine andere Anfrage.',{exact:true}).waitFor();
 job={...job,status:'awaiting_input',summary:'Welcher synthetische Raum ist gemeint?',activity:{phase:'input',message:'Welcher synthetische Raum ist gemeint?',can_cancel:true}};await activity.getByRole('button',{name:'Antwort schreiben',exact:true}).click();if(!await page.getByLabel('Nachricht',{exact:true}).evaluate(e=>e===document.activeElement))throw Error('Inline clarification does not focus composer');
 await page.keyboard.press('Tab');job={...job,status:'awaiting_approval',steps:[{sequence:1,kind:'effect',status:'prepared',sha256:'a'.repeat(64),document:{message:'Synthetischer Schritt'},result:{}}],activity:{phase:'approval',message:'Ein Schritt wartet auf deine Freigabe.',can_cancel:true}};await activity.getByRole('button',{name:'Schritt prüfen und freigeben',exact:true}).click();const approve=page.getByRole('button',{name:'Diesen Schritt freigeben und fortsetzen',exact:true});await approve.waitFor();if(!await approve.evaluate(e=>e===document.activeElement))throw Error('Inline approval does not reveal/focus actual approval');await details.locator(':scope > summary').click();
 job={...job,status:'running',steps:job.steps.map(step=>({...step,status:'succeeded',approved:true})),activity:{phase:'reading',message:'Synthetische Daten werden gelesen.',can_cancel:true}};await activity.getByText(job.activity.message,{exact:true}).waitFor();await activity.getByRole('button',{name:'Abbrechen',exact:true}).click();await activity.getByRole('button',{name:'Abbruch angefordert',exact:true}).waitFor();if(cancelled!==1||!await activity.getByRole('button',{name:'Abbruch angefordert',exact:true}).isDisabled())throw Error('Cancellation replay or missing acknowledgement');
 job={...job,id:'00000000-0000-0000-0000-000000000103',created:100,steps:[],status:'failed',cancel_requested:false,summary:'Das lokale Modell ist derzeit nicht erreichbar.',activity:{phase:'failed',message:'Das lokale Modell ist derzeit nicht erreichbar.',next_action:'Prüfe das Modell in den Einstellungen.',can_cancel:false}};await activity.getByText('Prüfe das Modell in den Einstellungen.',{exact:true}).waitFor();await activity.getByRole('button',{name:'Frage erneut vorbereiten',exact:true}).click();if(await page.getByLabel('Nachricht',{exact:true}).inputValue()!==job.goal)throw Error('Explicit retry preparation lost goal');if(created||writeCalls)throw Error('Retry preparation dispatched a job');
 // No activity DTO: legacy servers retain honest status-derived feedback.
 job={...job,id:'00000000-0000-0000-0000-000000000104',created:120,status:'running',steps:[],activity:undefined};await activity.getByText('Der Auftrag wird vorbereitet.',{exact:true}).waitFor();
 pollUnavailable=true;await activity.getByText('Live-Status ist gerade nicht erreichbar. Angezeigt wird der letzte bekannte Stand.',{exact:true}).waitFor();pollUnavailable=false;await activity.getByText('Der Auftrag wird vorbereitet.',{exact:true}).waitFor();
 // Explicit uncertain reconciliation creates one READ-ONLY job; an older held poll cannot undo it.
 job={...job,status:'uncertain',summary:'Die Wirkung des synthetischen Auftrags ist unklar.',steps:[{sequence:2,kind:'effect',status:'uncertain',sha256:'a'.repeat(64),document:{},result:{}}],activity:{phase:'uncertain',message:'Die Wirkung ist noch unklar.',can_cancel:false}};await activity.getByRole('button',{name:'Zustand prüfen',exact:true}).waitFor();
 const uncertainId=job.id;const oldStarted=new Promise(resolve=>markOldPoll=resolve);holdOldPoll=true;await oldStarted;
 let reconcileCalls=0,releaseReconcile;
 await page.route(base+'/api/conversations/'+chat.id+'/agent-runs',async route=>{reconcileCalls++;const body=route.request().postDataJSON();if(body.read_only!==true||body.research_allowed!==false||body.reconcile_job_id!==uncertainId||!body.request_id)throw Error('Reconciliation lost read-only identity');await new Promise(resolve=>releaseReconcile=resolve);job={...job,id:'00000000-0000-0000-0000-000000000102',created:200,status:'queued',cancel_requested:false,steps:[],activity:{phase:'queued',message:'Der tatsächliche Zustand wird nur lesend geprüft.',can_cancel:true}};await route.fulfill({json:job})});
 await activity.getByRole('button',{name:'Zustand prüfen',exact:true}).click();const preparing=activity.getByRole('button',{name:'Zustandsprüfung wird vorbereitet …',exact:true});await preparing.waitFor();if(!await preparing.isDisabled())throw Error('Reconciliation allows duplicate submission');await preparing.dispatchEvent('click');releaseReconcile();await activity.getByText('Der tatsächliche Zustand wird nur lesend geprüft.',{exact:true}).waitFor();releaseOldPoll();await page.waitForTimeout(2300);if(reconcileCalls!==1||!await activity.getByText('Der tatsächliche Zustand wird nur lesend geprüft.',{exact:true}).isVisible())throw Error('Stale uncertain poll replaced accepted reconciliation or duplicated request');
 const dispatchesBeforeClassification=created;
 // Slow classification has its own truthful visible state BEFORE any job/messages POST.
 job={...job,status:'observed',summary:'Die synthetische Abfrage ist abgeschlossen.',activity:{phase:'completed',message:'Abfrage abgeschlossen.',can_cancel:false}};await page.reload();await activity.waitFor({state:'hidden'});await details.locator(':scope > summary').getByText('Abfrage abgeschlossen · 1 Auftrag',{exact:true}).waitFor();if(await details.evaluate(el=>el.open))throw Error('Completed read expanded details');
 await page.route(base+'/api/conversations/'+chat.id+'/integration-route',async route=>{if(route.request().postDataJSON().model_mode!=='auto')throw Error('Composer mode missing from classification');routePending=true;await new Promise(resolve=>releaseRoute=resolve);await route.fulfill({status:503,json:{detail:'Synthetisch abgebrochene Einordnung'}}).catch(()=>{})});
 await page.getByLabel('Nachricht',{exact:true}).fill('Neue synthetische Frage');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await activity.getByText('Anfrage wird eingeordnet',{exact:true}).waitFor();if(!routePending||created!==dispatchesBeforeClassification)throw Error('Preparation was not visible before classification/job creation');await activity.getByRole('button',{name:'Abbrechen',exact:true}).click();releaseRoute();await page.getByRole('button',{name:'Nachricht senden',exact:true}).waitFor();if(created!==dispatchesBeforeClassification||await page.getByLabel('Nachricht',{exact:true}).inputValue()!=='Neue synthetische Frage')throw Error('Cancelled classification dispatched or lost draft');
 for(const width of [320,390,1440]){await page.setViewportSize({width,height:740});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Activity horizontal overflow at '+width);if(await activity.isVisible()||!await page.getByLabel('Nachricht',{exact:true}).isVisible())throw Error('Completed status adds clutter or composer unreachable at '+width)}
 unrelatedResponse=true;await page.reload();await page.getByLabel('Nachricht',{exact:true}).waitFor();await activity.waitFor({state:'hidden'});if(await details.evaluate(e=>e.open))throw Error('Unrelated response reopened old job details');
 if(errors.length||writeCalls)throw Error('Activity page errors or unexpected writes');console.log('Agent activity passed: immediate honest phases, explicit model wait, live reading feedback outside collapsed details, accessible clarification/approval, once-only cancel acknowledgement, explicit retry draft only, legacy fallback and mobile320/390/desktop1440. Synthetic only.');
 }finally{await browser.close()}
}
