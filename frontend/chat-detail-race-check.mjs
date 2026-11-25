// Real React/auth/conversation APIs on a fresh isolated synthetic fixture.
// Agent jobs and displayed messages are synthetic stubs; no live targets or model calls.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,realpath,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:net';
const base='http://127.0.0.1:18839',pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let server,serverExit,folder,serverLog='',startError;
const stop=()=>{if(server?.pid&&server.exitCode===null&&!server.signalCode)server.kill('SIGTERM')};
const interrupt=()=>{stop();process.exit(130)},terminate=()=>{stop();process.exit(143)};
try{
 await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',error=>reject(Error('Chat detail race fixture port18839 unavailable ('+error.code+'); existing service untouched')));probe.listen(18839,'127.0.0.1',()=>probe.close(resolve));});
 folder=await realpath(await mkdtemp(join(tmpdir(),'obdaai-chat-detail-race-')));
 const root=fileURLToPath(new URL('../',import.meta.url));
 const python=process.env.HUB_TEST_PYTHON?resolve(process.env.HUB_TEST_PYTHON):fileURLToPath(new URL('../.venv/bin/python',import.meta.url));
 server=spawn(python,['-m','uvicorn','scripts.browser_fixture:app','--host','127.0.0.1','--port','18839'],{cwd:root,env:{...process.env,HUB_BROWSER_FIXTURE_DIR:folder,HUB_BROWSER_ORIGIN:base},stdio:['ignore','pipe','pipe']});
 serverExit=new Promise(resolve=>server.once('close',resolve));server.once('error',e=>{startError=e;});
 for(const stream of [server.stdout,server.stderr])stream.on('data',chunk=>{serverLog=(serverLog+chunk.toString()).slice(-6000);});
 process.once('exit',stop);process.once('SIGINT',interrupt);process.once('SIGTERM',terminate);
 const deadline=Date.now()+30000;let healthy=false;
 while(Date.now()<deadline){if(startError)throw startError;if(server.exitCode!==null||server.signalCode)throw Error('Owned fixture stopped: '+serverLog);try{healthy=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok;}catch{}if(healthy)break;await pause(100);}
 if(!healthy)throw Error('Owned Chat detail race fixture startup timed out: '+serverLog);
 await checks();
}finally{
 if(server){stop();let timer;try{await Promise.race([serverExit,new Promise(resolve=>{timer=setTimeout(resolve,5000);})]);}finally{clearTimeout(timer);}if(server.pid&&server.exitCode===null&&!server.signalCode){server.kill('SIGKILL');await serverExit;}}
 process.removeListener('exit',stop);process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',terminate);
 if(folder)await rm(folder,{recursive:true,force:true});
}
async function checks(){
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.setDefaultTimeout(20000);page.on('pageerror',error=>errors.push(error.message));
 try{
 await page.goto(base);await page.getByLabel('Passwort',{exact:true}).fill('synthetic-ui-password');const login=page.waitForResponse(r=>r.url()===base+'/api/login'&&r.request().method()==='POST');await page.getByRole('button',{name:'Anmelden',exact:true}).click();const auth=await(await login).json(),headers={'X-CSRF-Token':auth.csrf,Origin:base};await page.getByRole('button',{name:'Abmelden',exact:true}).waitFor();
 const result=await page.request.post(base+'/api/conversations',{headers,data:{}});if(!result.ok())throw Error('Owned synthetic conversation create failed');const chat=await result.json();
 const goal='Prüfe den synthetischen Zustand.',answer='Der synthetische Zustand wurde abschließend geprüft.',nextGoal='Eine eigene neue synthetische Frage',nextAnswer='Neue gewöhnliche synthetische Antwort.';
 const user={id:'old-user',role:'user',content:goal,label:'LOCAL_ONLY',revision:1};
 let detail={...chat,title:'Synthetische Refresh-Prüfung',messages:[user],runs:[]};
 let job={id:'00000000-0000-0000-0000-000000000501',created:100,status:'running',goal,summary:'',cancel_requested:false,steps:[],activity:{phase:'planning',message:'Synthetische Planung läuft.',event_key:'running0',can_cancel:true}};
 let holdNext=false,held,release,posts=0,releaseMessage,messageEntered,agentPosts=0;
 const holdDetail=()=>new Promise(resolve=>{held=resolve;holdNext=true});
 const waitFrame=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 await page.route(base+'/api/agent-runs?*',route=>route.fulfill({json:[job]}));
 await page.route(base+'/api/conversations/'+chat.id,async route=>{if(route.request().method()==='PATCH'){const response=await route.fetch();if(response.ok()){const actual=await(await page.request.get(base+'/api/conversations/'+chat.id)).json();detail={...detail,title:actual.title,title_status:actual.title_status,archived:actual.archived}};return route.fulfill({response})}if(route.request().method()!=='GET')return route.continue();const snapshot=structuredClone(detail);if(holdNext){holdNext=false;held();await new Promise(resolve=>release=resolve)}await route.fulfill({json:snapshot})});
 await page.route(base+'/api/conversations/'+chat.id+'/integration-route',route=>route.fulfill({json:{route:route.request().postDataJSON().goal==='Zweite synthetische Agentenfrage'?'agent':'chat',integration_ids:['synthetic-target']}}));
 await page.route(base+'/api/conversations/'+chat.id+'/messages',async route=>{posts++;if(route.request().postDataJSON().content!==nextGoal)throw Error('Own request lost goal');messageEntered();await new Promise(resolve=>releaseMessage=resolve);detail={...detail,messages:[...detail.messages,{id:'new-user',role:'user',content:nextGoal,label:'LOCAL_ONLY',revision:1},{id:'new-answer',role:'assistant',content:nextAnswer,label:'LOCAL_ONLY',revision:1}]};await route.fulfill({contentType:'text/event-stream',body:'event: delta\ndata: '+JSON.stringify({text:nextAnswer})+'\n\nevent: done\ndata: {"status":"succeeded"}\n\n'})});
 await page.goto(base+'/?chat='+chat.id);const activity=page.getByRole('region',{name:'Aktueller Auftrag',exact:true}),composer=page.getByLabel('Nachricht',{exact:true});await activity.getByText('Synthetische Planung läuft.',{exact:true}).waitFor();
 // Capture an older running detail before the newer terminal receipt exists.
 const runningHeld=holdDetail();job={...job,activity:{...job.activity,event_key:'running1',message:'Ein synthetischer Schritt läuft.'}};await runningHeld;
 detail={...detail,messages:[user,{id:'agent-answer',role:'assistant',content:answer,label:'LOCAL_ONLY',revision:1,processing:{agent_job_id:job.id,provider:'local',model_used:false,status:'succeeded'}}]};job={...job,status:'observed',summary:answer,activity:{phase:'completed',message:'Abgeschlossen.',event_key:'observed2',can_cancel:false}};
 await page.getByRole('region',{name:'Gespräch',exact:true}).getByText(answer,{exact:true}).waitFor();await activity.waitFor({state:'hidden'});
 const releasedRunning=page.waitForResponse(r=>r.url()===base+'/api/conversations/'+chat.id);release();await(await releasedRunning).finished();await waitFrame();
 if(!await page.getByRole('region',{name:'Gespräch',exact:true}).getByText(answer,{exact:true}).isVisible())throw Error('Older running detail rolled back the newer terminal answer');
 // A second old detail must not remove a foreground optimistic same-chat send.
 const terminalHeld=holdDetail();job={...job,activity:{...job.activity,event_key:'observed3'}};await terminalHeld;
 const messageStarted=new Promise(resolve=>messageEntered=resolve);await composer.fill(nextGoal);await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await messageStarted;await page.getByText(nextGoal,{exact:true}).waitFor();await composer.fill('Ungesendeter eigener Entwurf bleibt erhalten');
 const releasedTerminal=page.waitForResponse(r=>r.url()===base+'/api/conversations/'+chat.id);release();await(await releasedTerminal).finished();await waitFrame();
 if(!await page.getByText(nextGoal,{exact:true}).isVisible()||await page.locator('.message.assistant').last().textContent()===answer||await composer.inputValue()!=='Ungesendeter eigener Entwurf bleibt erhalten'||!await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).isVisible())throw Error('Background detail replaced an optimistic own turn or its draft/controller');
 releaseMessage();await page.getByText(nextAnswer,{exact:true}).waitFor();await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).waitFor({state:'hidden'});
 if(posts!==1||await composer.inputValue()!=='Ungesendeter eigener Entwurf bleibt erhalten'||!await page.getByText(nextGoal,{exact:true}).isVisible()||errors.length)throw Error('Own turn replayed or lost draft/messages after background refresh');
 // Do not drop the terminal signature while foreground acceptance owns a GET.
 const secondAnswer='Zweiter synthetischer Auftrag vollständig beantwortet.';
 await page.route(base+'/api/conversations/'+chat.id+'/agent-runs',async route=>{agentPosts++;job={...job,id:'00000000-0000-0000-0000-000000000502',created:200,status:'queued',goal:'Zweite synthetische Agentenfrage',summary:'',steps:[],activity:{phase:'queued',message:'Zweiter synthetischer Auftrag wartet.',event_key:'second-queued',can_cancel:true}};await route.fulfill({json:job})});
 const acceptanceHeld=holdDetail();await composer.fill('Zweite synthetische Agentenfrage');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await acceptanceHeld;await activity.getByText('Zweiter synthetischer Auftrag wartet.',{exact:true}).waitFor();
 detail={...detail,messages:[...detail.messages,{id:'second-agent-user',role:'user',content:job.goal,label:'LOCAL_ONLY',revision:1},{id:'second-agent-answer',role:'assistant',content:secondAnswer,label:'LOCAL_ONLY',revision:1,processing:{agent_job_id:job.id,provider:'local',model_used:false,status:'succeeded'}}]};job={...job,status:'observed',summary:secondAnswer,activity:{phase:'completed',message:'Abgeschlossen.',event_key:'second-terminal',can_cancel:false}};
 await page.locator('[data-agent-job="'+job.id+'"] > summary').filter({hasText:'Nur lesende Schritte abgeschlossen'}).waitFor({state:'attached'});
 const releasedAcceptance=page.waitForResponse(r=>r.url()===base+'/api/conversations/'+chat.id);release();await(await releasedAcceptance).finished();await page.getByRole('region',{name:'Gespräch',exact:true}).getByText(secondAnswer,{exact:true}).waitFor();await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).waitFor({state:'hidden'});
 if(agentPosts!==1||posts!==1||errors.length)throw Error('Deferred terminal refresh was lost or accepted request replayed');
 // Older background snapshots cannot undo real local rename/archive receipts.
 const renameHeld=holdDetail();job={...job,activity:{...job.activity,event_key:'before-rename'}};await renameHeld;
 await page.getByRole('button',{name:'Gespräch umbenennen',exact:true}).click();await page.getByLabel('Titel',{exact:true}).fill('Bewusst umbenannter synthetischer Chat');await page.getByRole('button',{name:'Speichern',exact:true}).click();await page.locator('.chat-top .context').getByText('Bewusst umbenannter synthetischer Chat',{exact:true}).waitFor();
 const renameOld=page.waitForResponse(r=>r.url()===base+'/api/conversations/'+chat.id);release();await(await renameOld).finished();await waitFrame();if(!await page.locator('.chat-top .context').getByText('Bewusst umbenannter synthetischer Chat',{exact:true}).isVisible())throw Error('Older detail reverted the manual title');
 const archiveHeld=holdDetail();job={...job,activity:{...job.activity,event_key:'before-archive'}};await archiveHeld;await page.getByRole('button',{name:'Gespräch archivieren',exact:true}).click();await page.getByRole('button',{name:'Gespräch wieder öffnen',exact:true}).waitFor();const archiveOld=page.waitForResponse(r=>r.url()===base+'/api/conversations/'+chat.id);release();await(await archiveOld).finished();await waitFrame();
 const stored=await(await page.request.get(base+'/api/conversations/'+chat.id)).json();if(!await page.getByRole('button',{name:'Gespräch wieder öffnen',exact:true}).isVisible()||!await composer.isDisabled()||!stored.archived||stored.title!=='Bewusst umbenannter synthetischer Chat')throw Error('Older detail reverted archive UI or real owned metadata '+JSON.stringify({archiveButton:await page.getByRole('button',{name:'Gespräch wieder öffnen',exact:true}).isVisible(),composerDisabled:await composer.isDisabled(),storedArchived:stored.archived,titleMatches:stored.title==='Bewusst umbenannter synthetischer Chat'}));
 console.log('Chat detail race passed: held running snapshot cannot overwrite newer terminal answer; held terminal snapshot cannot remove same-chat optimistic user/stream or unsent draft/controller. Terminal poll during held foreground acceptance is drained after the turn. Real owned rename/archive receipts also survive held older details. One ordinary and one agent submission, no replay. Real React/auth/conversation API with synthetic job/detail/SSE contracts, no target/model calls.');
 }finally{await browser.close()}
}
