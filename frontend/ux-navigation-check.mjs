import {getSystemMode,setSystemMode} from './composer-agent-mode.mjs';
// Real React, authentication and conversation creation on a fresh synthetic fixture.
// Integration routing and terminal HA read responses are stubbed; no live HA acceptance.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,realpath,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:net';
const base='http://127.0.0.1:18817',pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let server,serverExit,folder,serverLog='',startError;
const stop=()=>{if(server?.pid&&server.exitCode===null&&!server.signalCode)server.kill('SIGTERM')};
const interrupt=()=>{stop();process.exit(130)},terminate=()=>{stop();process.exit(143)};
try{
 await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',error=>reject(Error('HA access fixture port18817 unavailable ('+error.code+'); existing service untouched')));probe.listen(18817,'127.0.0.1',()=>probe.close(resolve));});
 folder=await realpath(await mkdtemp(join(tmpdir(),'obdaai-ux-navigation-')));
 const root=fileURLToPath(new URL('../',import.meta.url));
 const python=process.env.HUB_TEST_PYTHON?resolve(process.env.HUB_TEST_PYTHON):fileURLToPath(new URL('../.venv/bin/python',import.meta.url));
 server=spawn(python,['-m','uvicorn','scripts.browser_fixture:app','--host','127.0.0.1','--port','18817'],{cwd:root,env:{...process.env,HUB_BROWSER_FIXTURE_DIR:folder,HUB_BROWSER_ORIGIN:base},stdio:['ignore','pipe','pipe']});
 serverExit=new Promise(resolve=>server.once('close',resolve));server.once('error',e=>{startError=e;});
 for(const stream of [server.stdout,server.stderr])stream.on('data',chunk=>{serverLog=(serverLog+chunk.toString()).slice(-6000);});
 process.once('exit',stop);process.once('SIGINT',interrupt);process.once('SIGTERM',terminate);
 const deadline=Date.now()+30000;let healthy=false;
 while(Date.now()<deadline){if(startError)throw startError;if(server.exitCode!==null||server.signalCode)throw Error('Owned fixture stopped: '+serverLog);try{healthy=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok;}catch{}if(healthy)break;await pause(100);}
 if(!healthy)throw Error('Owned HA access fixture startup timed out: '+serverLog);
 await checks();
 if(process.env.HUB_UX_PROFILE_CHECK==='true'){process.env.PROFILE_FIXTURE_URL=base;await import('./profile-check.mjs')}
}finally{
 if(server){stop();let timer;try{await Promise.race([serverExit,new Promise(resolve=>{timer=setTimeout(resolve,5000);})]);}finally{clearTimeout(timer);}if(server.pid&&server.exitCode===null&&!server.signalCode){server.kill('SIGKILL');await serverExit;}}
 process.removeListener('exit',stop);process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',terminate);
 if(folder)await rm(folder,{recursive:true,force:true});
}
async function checks(){
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1366,height:1050}}),errors=[];
 page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
 const confirm=()=>page.getByRole('dialog',{name:'Ungespeicherte Änderungen',exact:true});
 try{
 await page.goto(base);await page.getByLabel('Passwort',{exact:true}).fill('synthetic-ui-password');const login=page.waitForResponse(response=>response.url()===base+'/api/login'&&response.request().method()==='POST');await page.getByRole('button',{name:'Anmelden',exact:true}).click();const auth=await(await login).json();const headers={'X-CSRF-Token':auth.csrf,Origin:base};await page.getByRole('button',{name:'Abmelden',exact:true}).waitFor();
 // Cross-section navigation must retain the exact unsaved memory on cancel.
 await page.getByRole('button',{name:'Wissen',exact:true}).click();await page.getByRole('tab',{name:'Persönliche Merkliste',exact:true}).click();
 const memory=page.getByRole('region',{name:'Gedächtnis',exact:true});await memory.getByLabel('Titel',{exact:true}).fill('Synthetic unsaved memory');await memory.getByLabel('Memory-Inhalt',{exact:true}).fill('Keep this private synthetic draft.');
 await page.getByRole('tab',{name:'Wissensquellen',exact:true}).click();await confirm().waitFor();await page.keyboard.press('Escape');
 if(await memory.getByLabel('Memory-Inhalt',{exact:true}).inputValue()!=='Keep this private synthetic draft.')throw Error('Cross-tab cancel lost memory draft');
 await page.getByRole('button',{name:'Chat',exact:true}).click();await confirm().getByRole('button',{name:'Ohne Speichern weiter',exact:true}).click();await page.getByRole('textbox',{name:'Nachricht',exact:true}).waitFor();
 // Explicit administration choice belongs to one conversation only.
 await setSystemMode(page,true);await page.locator('.composer-note').getByText('Systemauftrag · lokal, ohne Cloudmodell',{exact:true}).waitFor();await page.getByRole('button',{name:'Neues Gespräch',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('.agent-mode input')?.checked);
 // Ordinary history traversal must retain its real forward entry when no editor is dirty.
 await page.getByRole('button',{name:'Einstellungen',exact:true}).click();await page.getByRole('button',{name:'Modelle',exact:true}).click();await page.getByRole('heading',{name:'Modelle und Verbindungen',exact:true}).waitFor();
 await page.getByRole('button',{name:'Wissen',exact:true}).click();await page.getByRole('heading',{name:'Wissen',exact:true,level:1}).waitFor();await page.goBack();await page.getByRole('heading',{name:'Einstellungen',exact:true,level:1}).waitFor();await page.goForward();await page.getByRole('heading',{name:'Wissen',exact:true,level:1}).waitFor();await page.getByRole('button',{name:'Chat',exact:true}).click();
 // The unsaved embedded task confirmation must remain above the mobile workbench.
 await page.setViewportSize({width:320,height:740});await page.getByLabel('Nachricht',{exact:true}).fill('Synthetic embedded task draft');await page.getByRole('button',{name:'Aktionen und Anhänge',exact:true}).click();await page.getByRole('menuitem',{name:/Aufgabe planen/}).click();
 const embedded=page.getByRole('region',{name:'Aufgabe bearbeiten',exact:true});await embedded.getByRole('button',{name:'Schließen',exact:true}).click();await confirm().getByRole('button',{name:'Weiter bearbeiten',exact:true}).click();if(!await embedded.isVisible())throw Error('Embedded dialog cancel lost task');
 await embedded.getByRole('button',{name:'Schließen',exact:true}).click();await confirm().getByRole('button',{name:'Ohne Speichern weiter',exact:true}).click();await page.getByRole('button',{name:'Arbeitsbereich schließen',exact:true}).click();await page.setViewportSize({width:1366,height:1050});
 // Persist an existing task, protect its editor and recover only its own draft.
 await page.getByRole('button',{name:'Aufgaben',exact:true}).click();const savedNewDraft=page.getByRole('button',{name:'Aufgabenentwurf verwerfen',exact:true});if(await savedNewDraft.isVisible())await savedNewDraft.click();else await page.getByRole('button',{name:'Neue Aufgabe',exact:true}).click();
 let editor=page.getByRole('dialog',{name:'Aufgabe bearbeiten',exact:true});await editor.waitFor();const embeddedRecovery=editor.getByRole('button',{name:'Aufgabenentwurf verwerfen',exact:true});if(await embeddedRecovery.isVisible())await embeddedRecovery.click();await editor.getByLabel('Name der Aufgabe',{exact:true}).fill('Synthetic recoverable task');await editor.getByLabel('Was soll erledigt werden?',{exact:true}).fill('Describe this synthetic workspace.');
 await editor.getByRole('button',{name:'Aufgabe anlegen',exact:true}).click();await page.getByRole('heading',{name:'Synthetic recoverable task',exact:true,level:2}).waitFor();await page.getByRole('button',{name:'Aufgabe bearbeiten',exact:true}).click();
 editor=page.getByRole('dialog',{name:'Aufgabe bearbeiten',exact:true});await editor.getByLabel('Was soll erledigt werden?',{exact:true}).fill('Synthetic changed goal retained in this tab.');
 await page.keyboard.press('Escape');await confirm().waitFor();await confirm().getByRole('button',{name:'Weiter bearbeiten',exact:true}).click();
 if(await editor.getByLabel('Was soll erledigt werden?',{exact:true}).inputValue()!=='Synthetic changed goal retained in this tab.')throw Error('Task cancel lost editor');
 await page.keyboard.press('Escape');await confirm().getByRole('button',{name:'Ohne Speichern weiter',exact:true}).click();
 await page.getByRole('region',{name:'Gesicherter Aufgabenentwurf',exact:true}).getByRole('button',{name:'Bearbeitung fortsetzen',exact:true}).click();
 editor=page.getByRole('dialog',{name:'Aufgabe bearbeiten',exact:true});if(await editor.getByLabel('Was soll erledigt werden?',{exact:true}).inputValue()!=='Synthetic changed goal retained in this tab.')throw Error('Existing task draft was not recoverable');
 // Keyboard focus remains inside the top dialog, including at mobile width.
 await page.setViewportSize({width:320,height:740});await page.keyboard.press('Tab');if(!await editor.evaluate(node=>node.contains(document.activeElement)))throw Error('Dialog lost keyboard focus');
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile navigation dialog overflow');
 const shots=fileURLToPath(new URL('../.local/browser/',import.meta.url));await mkdir(shots,{recursive:true});await page.screenshot({path:join(shots,'ux-task-recovery.png'),fullPage:true,animations:'disabled'});
 // Ordinary Back navigation also protects editor contents and preserves the current URL on cancel.
 await page.setViewportSize({width:1366,height:1050});await page.keyboard.press('Escape');await confirm().getByRole('button',{name:'Ohne Speichern weiter',exact:true}).click();
 await page.getByRole('button',{name:'Wissen',exact:true}).click();await page.getByRole('tab',{name:'Persönliche Merkliste',exact:true}).click();await memory.getByLabel('Titel',{exact:true}).fill('Synthetic back-navigation draft');
 const currentURL=page.url();await page.goBack();await confirm().waitFor();await confirm().getByRole('button',{name:'Weiter bearbeiten',exact:true}).click();
 if(page.url()!==currentURL||await memory.getByLabel('Titel',{exact:true}).inputValue()!=='Synthetic back-navigation draft')throw Error('Back navigation lost draft or current route: '+JSON.stringify({url_kept:page.url()===currentURL,draft_kept:await memory.getByLabel('Titel',{exact:true}).inputValue()==='Synthetic back-navigation draft'}));
 await page.goBack();await confirm().getByRole('button',{name:'Ohne Speichern weiter',exact:true}).click();await page.waitForURL(url=>url.href!==currentURL);await page.goForward();await page.getByRole('heading',{name:'Wissen',exact:true,level:1}).waitFor();
 await page.getByRole('button',{name:'Chat',exact:true}).click();
 // A delayed refresh from an old agent conversation may never replace the newly opened conversation.
 const create=async title=>{const response=await page.request.post(base+'/api/conversations',{headers,data:{}});const item=await response.json();await page.request.patch(base+'/api/conversations/'+item.id,{headers,data:{title}});return item.id};
 const a=await create('Synthetic race A'),b=await create('Synthetic race B');const originalA=await(await page.request.get(base+'/api/conversations/'+a)).json();
 let polls=0,release,started;const delayed=new Promise(resolve=>{started=resolve}),gate=new Promise(resolve=>{release=resolve});let hold=false;
 await page.route(base+'/api/agent-runs?conversation_id='+a,route=>{polls++;return route.fulfill({json:[{id:'81dfe0a1-0d0f-4866-a6d6-fb7846849013',status:polls===1?'running':'observed',goal:'Synthetic read',summary:'Synthetic completed read',cancel_requested:false,steps:[]}]})});
 await page.route(base+'/api/conversations/'+a,async route=>{if(hold){started();await gate;return route.fulfill({json:originalA})}return route.continue()});
 await page.goto(base+'/?chat='+a);await page.getByText('Synthetic race A',{exact:true}).first().waitFor();hold=true;await delayed;
 await page.locator('.history-open').filter({hasText:'Synthetic race B'}).click();await page.locator('.chat-top .context').filter({hasText:'Synthetic race B'}).waitFor();release();await pause(150);
 if(!await page.locator('.chat-top .context').filter({hasText:'Synthetic race B'}).isVisible())throw Error('Old agent refresh replaced current conversation');
 // An acknowledged cancellation for A may finish after B opens, without assigning A's job to B.
 await page.unroute(base+'/api/agent-runs?conversation_id='+a);await page.unroute(base+'/api/conversations/'+a);
 const cancelId='91dfe0a1-0d0f-4866-a6d6-fb7846849013';let cancelCalls=0,cancelAcknowledged=false,releaseCancel,enteredCancel;
 const cancelEntered=new Promise(resolve=>{enteredCancel=resolve}),cancelGate=new Promise(resolve=>{releaseCancel=resolve});
 const originalJob=()=>({id:cancelId,status:'running',goal:'Synthetic independent A read',summary:'Synthetic read in progress',cancel_requested:cancelAcknowledged,steps:[]});
 await page.route(base+'/api/agent-runs?conversation_id='+a,route=>route.fulfill({json:[originalJob()]}));
 await page.route(base+'/api/agent-runs/'+cancelId+'/cancel',async route=>{cancelCalls++;enteredCancel();await cancelGate;cancelAcknowledged=true;return route.fulfill({json:originalJob()})});
 await page.goto(base+'/?chat='+a);await page.getByRole('region',{name:'Details Abarbeitung',exact:true}).locator('.agent-work-summary').click();await page.locator('details[data-agent-job] > summary').click();await page.getByRole('button',{name:'Agentenlauf abbrechen',exact:true}).click();await cancelEntered;
 const initialBPoll=page.waitForResponse(response=>response.url()===base+'/api/agent-runs?conversation_id='+b&&response.request().method()==='GET');await page.locator('.history-open').filter({hasText:'Synthetic race B'}).click();await(await initialBPoll).finished();await page.locator('.chat-top .context').filter({hasText:'Synthetic race B'}).waitFor();await page.getByLabel('Nachricht',{exact:true}).fill('Synthetic independent B question');
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));const cancelResponse=page.waitForResponse(response=>response.url()===base+'/api/agent-runs/'+cancelId+'/cancel');releaseCancel();await(await cancelResponse).finished();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 if(!cancelAcknowledged||cancelCalls!==1)throw Error('Original A cancellation was lost or replayed');if(!await page.getByRole('button',{name:'Nachricht senden',exact:true}).isEnabled()||await page.getByLabel('Nachricht',{exact:true}).inputValue()!=='Synthetic independent B question')throw Error('Delayed accepted A action changed B agent state');
 // Failed semantic interpretation preserves the prompt and dispatches neither ordinary chat nor agent.
 let blockedDispatches=0;
 let releaseRouting;const routingGate=new Promise(resolve=>{releaseRouting=resolve});await page.route(base+'/api/conversations/'+b+'/integration-route',async route=>{await routingGate;return route.fulfill({status:503,json:{detail:'Die Anfrage konnte gerade nicht zuverlässig zugeordnet werden. Bitte später erneut versuchen.'}})});
 const blockSend=route=>{blockedDispatches++;return route.fulfill({status:500,json:{detail:'Unexpected synthetic dispatch'}})};
 await page.route(base+'/api/conversations/'+b+'/messages',blockSend);await page.route(base+'/api/conversations/'+b+'/agent-runs',blockSend);
 await page.getByLabel('Nachricht',{exact:true}).fill('Synthetic intent service unavailable');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await page.getByText('Anfrage wird eingeordnet',{exact:true}).waitFor();releaseRouting();await page.getByRole('alert').filter({hasText:'Die Anfrage konnte gerade nicht zuverlässig zugeordnet werden.'}).waitFor();
 if(await page.getByLabel('Nachricht',{exact:true}).inputValue()!=='Synthetic intent service unavailable'||blockedDispatches!==0)throw Error('Failed routing lost draft or dispatched a fallback');
 await page.locator('.runtime-status').locator('summary').first().click();await page.getByText('Diese Anzeige liest nur vorhandene Betriebsdaten. Sie startet weder Modelltests noch Zugriffe auf deine Integrationen.',{exact:true}).waitFor();
 await page.unroute(base+'/api/conversations/'+b+'/messages',blockSend);await page.unroute(base+'/api/conversations/'+b+'/agent-runs',blockSend);
 // Contract stubs exercise new memory controls only; backend semantics have separate API tests.
 const mid='a5553420-7585-4a71-a0c5-b905a883d781',candidateId='b5553420-7585-4a71-a0c5-b905a883d781',learningId='c5553420-7585-4a71-a0c5-b905a883d781';
 let approved=false,retried=false,promoted=false;
 let remembered={id:mid,revision:1,title:'Synthetic archived memory',content:'Synthetic preferred response style',storage:'app',category:'preference',fact_type:'fact',sensitivity:'private',cloud_providers:[],status:'active',writable:true,origin:'conversation',provenance_status:'archived_origin',context_eligible:false,can_promote:true};
 await page.route(base+'/api/memories?*',route=>route.fulfill({json:[remembered]}));
 await page.route(base+'/api/memory-candidates',route=>route.fulfill({json:approved?[]:[{id:candidateId,revision:1,status:'pending',fresh:true,preview:'Synthetic changed preference',category:'preference',sensitivity:'private',confidence:1,source_message_revision:1,source_conversation_id:b,replacement_options:[{id:mid,revision:1,content:remembered.content}]}]}));
 await page.route(base+'/api/memory-candidates/'+candidateId+'/review',route=>{const body=route.request().postDataJSON();if(body.decision!=='approve'||body.replacement_memory_id!==mid||body.replacement_revision!==1)throw Error('Memory replacement did not bind selected revision');approved=true;return route.fulfill({json:{}})});
 await page.route(base+'/api/memory-learning-jobs',route=>route.fulfill({json:[{id:learningId,status:retried?'queued':'failed',error:retried?'':'local_extraction_unavailable',attempts:retried?2:1,current:true,retryable:!retried,source_conversation_id:b}]}));
 await page.route(base+'/api/memory-learning-jobs/'+learningId+'/retry',route=>{if(route.request().postDataJSON().expected_attempts!==1)throw Error('Learning retry omitted current attempt');retried=true;return route.fulfill({json:{}})});
 await page.route(base+'/api/memories/'+mid+'/promote',route=>{if(route.request().postDataJSON().expected_revision!==1)throw Error('Memory promotion omitted revision');promoted=true;remembered={...remembered,revision:2,provenance_status:'independent',context_eligible:true,can_promote:false};return route.fulfill({json:remembered})});
 await page.getByRole('button',{name:'Wissen',exact:true}).click();await page.getByRole('tab',{name:'Persönliche Merkliste',exact:true}).click();
 await memory.getByText('Synthetic changed preference',{exact:true}).waitFor();
 await memory.getByLabel('Vorhandene Erinnerung aktualisieren',{exact:true}).selectOption(mid);await memory.getByRole('button',{name:'Merken',exact:true}).click();if(!approved)throw Error('Explicit replacement not submitted');
 await memory.getByText('Lernen aus Gesprächen · 1 fehlgeschlagen',{exact:true}).click();await memory.getByRole('button',{name:'Lernen erneut versuchen',exact:true}).click();await memory.getByText('Wartet auf Verarbeitung · Versuch 2',{exact:true}).waitFor();
 await memory.locator('.memory-row').filter({hasText:'Synthetic archived memory'}).click();await memory.getByText('Herkunft und Gültigkeit',{exact:true}).click();await memory.getByText('Die Herkunft ist archiviert. Dieser Eintrag wird nicht als Antwortkontext verwendet.',{exact:true}).waitFor();await memory.getByRole('button',{name:'Als eigenständige Erinnerung behalten',exact:true}).click();await memory.getByText('Als eigenständige Erinnerung lokal gespeichert. Bisherige Cloudfreigaben wurden zurückgesetzt.',{exact:true}).waitFor();if(!retried||!promoted)throw Error('Memory recovery controls did not submit explicit bound intents');
 // Leaving through a provenance link must also protect unsaved learning settings.
 await memory.getByText('So lernt dein Gedächtnis',{exact:true}).click();const learningToggle=memory.getByRole('checkbox',{name:'Aus neuen Gesprächen lernen',exact:true}),previousLearning=await learningToggle.isChecked();await learningToggle.setChecked(!previousLearning);await memory.getByRole('button',{name:'Ursprüngliches Gespräch öffnen',exact:true}).first().click();await confirm().getByRole('button',{name:'Weiter bearbeiten',exact:true}).click();if(await learningToggle.isChecked()!==!previousLearning)throw Error('Provenance navigation lost memory settings draft');await learningToggle.setChecked(previousLearning);
 // Runtime diagnostics read the real fixture status; only the explicitly clicked planner probe is stubbed.
 await page.getByRole('button',{name:'Einstellungen',exact:true}).click();await page.getByRole('button',{name:'Modelle',exact:true}).click();
 const runtime=page.locator('.runtime-status');await runtime.locator('summary').first().click();await runtime.getByText('Erreichbar',{exact:true}).first().waitFor();
 const nativeStatus=await(await page.request.get(base+'/api/runtime-status')).json();if(nativeStatus.database.status!=='ok'||nativeStatus.local.planner_readiness!=='unknown')throw Error('Runtime endpoint conflated liveness and planner readiness');
 let plannerCalls=0;const probeId='d5553420-7585-4a71-a0c5-b905a883d781';
 await page.route(base+'/api/providers/*/test',route=>{const body=route.request().postDataJSON();if(body.mode!=='planner'||!body.request_id)throw Error('Planner test lost explicit mode or durable request identity');plannerCalls++;return route.fulfill({json:{id:probeId,status:'queued'}})});
 await page.route(base+'/api/provider-tests/'+probeId,route=>route.fulfill({json:{id:probeId,status:'succeeded',mode:'planner',result:'Synthetic planner schema check passed'}}));
 await page.getByRole('button',{name:'Planer prüfen',exact:true}).first().click();await page.getByText('Synthetic planner schema check passed',{exact:true}).waitFor();if(plannerCalls!==1)throw Error('Planner probe dispatched more than once');
 await page.route(base+'/api/runtime-status',route=>route.fulfill({json:{...nativeStatus,worker:{status:'stale'},intent_interpretation:{degraded:true},local:{configured:true,planner_readiness:'unknown',providers:[{id:'synthetic-local',idle_seconds:30,capacity:'busy',last_model_probe:{status:'succeeded',current_revision:true},last_planner_probe:null,planner_readiness:'unknown'}]}}}));
 await runtime.getByRole('button',{name:'Betriebsstatus aktualisieren',exact:true}).click();await runtime.getByText('Kein aktuelles Worker-Lebenszeichen',{exact:true}).waitFor();await runtime.getByText('Die automatische Zuordnung deiner Anfrage konnte zuletzt nicht zuverlässig ermittelt werden. Prüfe das lokale Modell und gegebenenfalls den Planer.',{exact:true}).waitFor();await runtime.getByText('Antwortmodell: Zuletzt bestanden · Planer: Noch nicht geprüft',{exact:true}).waitFor();await runtime.getByText('Gerade belegt. Neue lokale Aufträge können auf freie Verarbeitung warten.',{exact:true}).waitFor();await runtime.screenshot({path:join(shots,'runtime-status-ui.png'),animations:'disabled'});
 if(errors.length)throw Error(errors.join('\n'));
 console.log('UX navigation passed: synthetic real React/auth/API, cross-scope memory cancel/discard, per-chat administration mode, existing-task recovery, native Back/Forward and cancellation, delayed old agent refresh, accepted A-action/B-chat isolation and mobile dialog keyboard containment. Memory learning-settings provenance guard and routing503 draft/no-dispatch checks passed; new memory management and explicit planner probe use contract stubs; runtime diagnostics read the synthetic database; no live integrations.');
 }finally{await browser.close()}
}
