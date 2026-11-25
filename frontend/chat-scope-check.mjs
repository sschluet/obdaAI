// Real React, authentication and conversation creation on a fresh synthetic fixture.
// Integration routing is stubbed; streaming and deletion use the real synthetic API. No live targets.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,realpath,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:net';
const base='http://127.0.0.1:18819',pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let server,serverExit,folder,serverLog='',startError;
const stop=()=>{if(server?.pid&&server.exitCode===null&&!server.signalCode)server.kill('SIGTERM')};
const interrupt=()=>{stop();process.exit(130)},terminate=()=>{stop();process.exit(143)};
try{
 await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',error=>reject(Error('HA access fixture port18819 unavailable ('+error.code+'); existing service untouched')));probe.listen(18819,'127.0.0.1',()=>probe.close(resolve));});
 folder=await realpath(await mkdtemp(join(tmpdir(),'obdaai-chat-scope-')));
 const root=fileURLToPath(new URL('../',import.meta.url));
 const python=process.env.HUB_TEST_PYTHON?resolve(process.env.HUB_TEST_PYTHON):fileURLToPath(new URL('../.venv/bin/python',import.meta.url));
 server=spawn(python,['-m','uvicorn','scripts.browser_fixture:app','--host','127.0.0.1','--port','18819'],{cwd:root,env:{...process.env,HUB_BROWSER_FIXTURE_DIR:folder,HUB_BROWSER_ORIGIN:base},stdio:['ignore','pipe','pipe']});
 serverExit=new Promise(resolve=>server.once('close',resolve));server.once('error',e=>{startError=e;});
 for(const stream of [server.stdout,server.stderr])stream.on('data',chunk=>{serverLog=(serverLog+chunk.toString()).slice(-6000);});
 process.once('exit',stop);process.once('SIGINT',interrupt);process.once('SIGTERM',terminate);
 const deadline=Date.now()+30000;let healthy=false;
 while(Date.now()<deadline){if(startError)throw startError;if(server.exitCode!==null||server.signalCode)throw Error('Owned fixture stopped: '+serverLog);try{healthy=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok;}catch{}if(healthy)break;await pause(100);}
 if(!healthy)throw Error('Owned HA access fixture startup timed out: '+serverLog);
 await checks();
}finally{
 if(server){stop();let timer;try{await Promise.race([serverExit,new Promise(resolve=>{timer=setTimeout(resolve,5000);})]);}finally{clearTimeout(timer);}if(server.pid&&server.exitCode===null&&!server.signalCode){server.kill('SIGKILL');await serverExit;}}
 process.removeListener('exit',stop);process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',terminate);
 if(folder)await rm(folder,{recursive:true,force:true});
}
async function checks(){
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],posts=[];
 page.setDefaultTimeout(20000);page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{if(request.method()==='POST'&&/\/api\/conversations\/[^/]+\/(messages|retry)$/.test(new URL(request.url()).pathname))posts.push({path:new URL(request.url()).pathname,body:request.postDataJSON()})});
 try{
 await page.goto(base);await page.getByLabel('Passwort',{exact:true}).fill('synthetic-ui-password');const logged=page.waitForResponse(response=>response.url()===base+'/api/login'&&response.request().method()==='POST');await page.getByRole('button',{name:'Anmelden',exact:true}).click();const auth=await(await logged).json(),headers={'X-CSRF-Token':auth.csrf,Origin:base};await page.getByRole('button',{name:'Abmelden',exact:true}).waitFor();
 const api=async(path,method='GET',data)=>{const response=await page.request.fetch(base+'/api'+path,{headers,method,...(data?{data}:{})});if(!response.ok())throw Error('Synthetic API '+method+' '+path+' '+response.status());return response.json()};
 const create=async title=>{const c=await api('/conversations','POST',{});await api('/conversations/'+c.id,'PATCH',{title});return {id:c.id,title}};
 const a=await create('Beispiel A'),b=await create('Beispiel B');let releaseRoute,routeEntered;const routeGate=new Promise(resolve=>{releaseRoute=resolve}),entered=new Promise(resolve=>{routeEntered=resolve});
 await page.route(base+'/api/conversations/*/integration-route',async route=>{if(route.request().postDataJSON().goal==='Synthetic delayed A routing'){routeEntered();await routeGate;return route.fulfill({status:503,json:{detail:'Synthetic A-only classification failure'}})}return route.fulfill({json:{route:'chat',integration_ids:[]}})});
 const composer=page.getByLabel('Nachricht',{exact:true});
 const open=async item=>{await page.locator('.history-open').filter({hasText:item.title}).click();await page.locator('.chat-top .context').filter({hasText:item.title}).waitFor()};
 const terminal=async(id,minimumRuns=1)=>{for(let n=0;n<90;n++){const c=await api('/conversations/'+id);if(c.runs.length>=minimumRuns&&!c.runs.some(run=>['queued','routing','streaming'].includes(run.status)))return c;await pause(300)}throw Error('Synthetic owned run not terminal within bound')};
 await page.goto(base+'/?chat='+a.id);await page.locator('.chat-top .context').filter({hasText:a.title}).waitFor();await composer.fill('Synthetic delayed A routing');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await entered;
 await open(b);await composer.fill('Synthetic B draft survives A');const oldRoute=page.waitForResponse(response=>response.url()===base+'/api/conversations/'+a.id+'/integration-route');releaseRoute();await(await oldRoute).finished();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 if(await composer.inputValue()!=='Synthetic B draft survives A'||!await page.getByRole('button',{name:'Nachricht senden',exact:true}).isEnabled()||await page.getByText('Synthetic A-only classification failure',{exact:true}).count())throw Error('Stale A route changed B draft/status/busy');
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await terminal(b.id);await page.getByRole('button',{name:'Nachricht senden',exact:true}).waitFor();if(posts.some(post=>post.path==='/api/conversations/'+a.id+'/messages'))throw Error('A routing failure dispatched a message');
 // Both streams use the real API and delayed synthetic provider; their same `stream` placeholder must remain owner-bound.
 await open(a);await composer.fill('SYNTHETIC_LONG_STREAM_RESPONSE owned A');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await page.locator('.message.assistant h3').filter({hasText:'Synthetischer Abschnitt 1'}).first().waitFor();await pause(2000);
 await open(b);await composer.fill('SYNTHETIC_LONG_STREAM_RESPONSE owned B');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await page.locator('.message.assistant h3').filter({hasText:'Synthetischer Abschnitt 1'}).first().waitFor();await composer.fill('Synthetic unsent B while A finishes');
 const aDone=await terminal(a.id);if(aDone.runs.at(-1).status!=='succeeded'||aDone.runs.length!==1)throw Error('Accepted A run was cancelled or replayed on navigation');
 const bWhileAFinished=await api('/conversations/'+b.id);if(!bWhileAFinished.runs.some(run=>['queued','routing','streaming'].includes(run.status)))throw Error('Synthetic fixture lost the intended overlapping run window');if(!await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).isVisible()||!await page.locator('.chat-top .context').filter({hasText:b.title}).isVisible())throw Error('A finalizer cleared B active controller or owner');
 const bDone=await terminal(b.id,2);await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).waitFor({state:'hidden'});const bLatest=page.locator('.message.assistant').last();
 if(await bLatest.locator('h3').count()!==48||await composer.inputValue()!=='Synthetic unsent B while A finishes'||bDone.runs.at(-1).status!=='succeeded')throw Error('A stream contaminated B or cleared its draft/controller');
 // The same scope contract applies to an accepted regeneration, including its final metadata fetch.
 await open(a);await page.getByRole('button',{name:'Antwort erneut erzeugen',exact:true}).click();await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).waitFor();await page.locator('.message.assistant h3').filter({hasText:'Synthetischer Abschnitt 1'}).first().waitFor();
 await open(b);await composer.fill('Synthetic independent B after regeneration');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await composer.fill('Synthetic final B draft');
 const regenDone=await terminal(a.id,2);const finalB=await terminal(b.id,3);await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).waitFor({state:'hidden'});
 if(regenDone.runs.at(-1).status!=='succeeded'||regenDone.runs.length!==2||finalB.runs.length!==3||await composer.inputValue()!=='Synthetic final B draft'||!await page.locator('.chat-top .context').filter({hasText:b.title}).isVisible())throw Error('A regeneration changed B owner/draft or was replayed');
 if(posts.filter(post=>post.path==='/api/conversations/'+a.id+'/messages').length!==1||posts.filter(post=>post.path==='/api/conversations/'+a.id+'/retry').length!==1)throw Error('Accepted A request replayed');
 // A real accepted deletion response may arrive after native History has opened B.
 await composer.fill('Synthetic B draft survives A deletion');await open(a);
 let releaseDelete,deleteEntered;const deleteGate=new Promise(resolve=>{releaseDelete=resolve}),deleteStarted=new Promise(resolve=>{deleteEntered=resolve});let deleteRequests=0;
 await page.route(base+'/api/conversations/'+a.id,async route=>{if(route.request().method()!=='DELETE')return route.continue();deleteRequests++;const response=await route.fetch();if(!response.ok())throw Error('Synthetic owned deletion rejected');deleteEntered();await deleteGate;return route.fulfill({response})});
 const aRow=page.locator('.history-row').filter({has:page.getByRole('button',{name:a.title,exact:true})});await aRow.locator('summary').click();await aRow.getByRole('button',{name:'Gespräch löschen',exact:true}).click();const deletion=page.getByRole('dialog',{name:'Gespräch endgültig löschen?',exact:true});await deletion.getByRole('button',{name:'Endgültig löschen',exact:true}).waitFor();await page.waitForFunction(()=>!document.querySelector('.delete-dialog .danger-button')?.disabled);await deletion.getByRole('button',{name:'Endgültig löschen',exact:true}).click();await deleteStarted;
 await page.goBack();await page.locator('.chat-top .context').filter({hasText:b.title}).waitFor();const deletionFinished=page.waitForResponse(response=>response.url()===base+'/api/conversations/'+a.id&&response.request().method()==='DELETE');releaseDelete();await(await deletionFinished).finished();await deletion.waitFor({state:'hidden'});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 if(deleteRequests!==1||await composer.inputValue()!=='Synthetic B draft survives A deletion'||!await page.locator('.chat-top .context').filter({hasText:b.title}).isVisible()||!await page.getByRole('button',{name:'Nachricht senden',exact:true}).isEnabled())throw Error('Delayed A deletion cleared B owner/draft/busy');
 if((await page.request.get(base+'/api/conversations/'+a.id)).status()!==404||(await api('/conversations/'+b.id)).runs.length!==3)throw Error('Synthetic deletion target or B retention changed');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Chat scope passed: delayed A route503 cannot restore draft/error/busy into B; real delayed A/B SSE placeholders stay separate; accepted A generation and regeneration persist once without navigation cancellation/replay; stale finalizers cannot clear B request/controller/draft; delayed real A deletion leaves History-selected B and its draft intact. Real isolated synthetic API/provider, no live targets.');
 }finally{await browser.close()}
}
