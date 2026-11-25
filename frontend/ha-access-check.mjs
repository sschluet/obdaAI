import {getSystemMode,setSystemMode} from './composer-agent-mode.mjs';
// Real React, authentication and conversation creation on a fresh synthetic fixture.
// Integration routing and terminal HA read responses are stubbed; no live HA acceptance.
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
 await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',error=>reject(Error('HA access fixture port18767 unavailable ('+error.code+'); existing service untouched')));probe.listen(18767,'127.0.0.1',()=>probe.close(resolve));});
 folder=await realpath(await mkdtemp(join(tmpdir(),'obdaai-ha-access-ui-')));
 const root=fileURLToPath(new URL('../',import.meta.url));
 const python=process.env.HUB_TEST_PYTHON?resolve(process.env.HUB_TEST_PYTHON):fileURLToPath(new URL('../.venv/bin/python',import.meta.url));
 server=spawn(python,['-m','uvicorn','scripts.browser_fixture:app','--host','127.0.0.1','--port','18767'],{cwd:root,env:{...process.env,HUB_BROWSER_FIXTURE_DIR:folder,HUB_BROWSER_ORIGIN:base},stdio:['ignore','pipe','pipe']});
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
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1366,height:1050}}),errors=[];
 page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
 const iid='74d8d5a4-940a-4e28-a1b5-12f1c46348ea',goal='Kannst Du auf Home Assistant zugreifen?';
 const success='Ja, Home Assistant ist erreichbar. Die Anmeldung funktioniert.';
 const failure='Lesezugriff fehlgeschlagen. Die Verbindung zum Zielsystem konnte nicht hergestellt werden.';
 const jobs=new Map();let scenario='success',creates=0,routes=0,submissions=0,forbidden=0;
 const json=(route,body)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
 try{
  await page.route(base+'/api/**',async route=>{
   const request=route.request(),u=new URL(request.url()),path=u.pathname,method=request.method();
   if(path==='/api/integrations'&&method==='GET')return json(route,{integrations:[{id:iid,name:'Home Assistant Aurora',kind:'home_assistant',revision:1,enabled:true,writes_enabled:false,secret_saved:true,check_available:true,execution_available:true,config:{}}]});
   if(/^\/api\/integration-bindings\/conversation\//.test(path)&&method==='GET')return json(route,{revision:0,integration_ids:[],selection_mode:'automatic',effective_selection_mode:'automatic',effective_integration_ids:[iid],execution_available:true});
   if(path==='/api/conversations'&&method==='POST')creates++;
   if(path.endsWith('/integration-route')&&method==='POST'){
    routes++;if(request.postDataJSON().goal!==goal)throw Error('HA request changed before routing');
    return json(route,{route:'agent',integration_ids:[iid]});
   }
   const submit=path.match(/^\/api\/conversations\/([^/]+)\/agent-runs$/);
   if(submit&&method==='POST'){
    submissions++;const body=request.postDataJSON();
    if(body.goal!==goal||JSON.stringify(body.integration_ids)!==JSON.stringify([iid])||!body.request_id)throw Error('Automatic HA selection/request identity missing');
    const good=scenario==='success',job={id:crypto.randomUUID(),status:good?'observed':'failed',goal,summary:good?success:failure,cancel_requested:false,steps:[{sequence:1,kind:'read',status:good?'succeeded':'failed',sha256:'a'.repeat(64),document:{kind:'tool',tool:'http',message:'Freigegebene Verbindung ausschließlich lesend prüfen',integration_id:iid,arguments:{method:'GET',path:'/api/'},capability_inspection:true,target:{kind:'home_assistant',profile_revision:1,config_sha256:'b'.repeat(64)}},result:good?{http_status:200,body:{message:'API running.'},effect_verified:false}:{failure_category:'connection_failed',automatic_retry:false,effect_verified:false}}]};
    jobs.set(submit[1],job);return json(route,job);
   }
   if(path==='/api/agent-runs'&&method==='GET')return json(route,jobs.has(u.searchParams.get('conversation_id'))?[jobs.get(u.searchParams.get('conversation_id'))]:[]);
   if(/^\/api\/agent-runs\/[^/]+\/steps\/1$/.test(path)&&method==='GET'){
    const job=[...jobs.values()].find(j=>j.id===path.split('/')[3]);return json(route,{document:job.steps[0].document,result:job.steps[0].result});
   }
   if(/^\/api\/conversations\/[^/]+$/.test(path)&&method==='GET'){
    const response=await route.fetch(),detail=await response.json(),job=jobs.get(path.split('/')[3]);
    if(job)detail.messages=[...detail.messages,{id:job.id+'-u',role:'user',content:goal,label:'LOCAL_ONLY',revision:1,processing:null},{id:job.id+'-a',role:'assistant',content:job.summary,label:'LOCAL_ONLY',revision:1,processing:{run_id:'',provider:'local',model:null,model_used:false,status:'succeeded',agent_job_id:job.id}}];
    return json(route,detail);
   }
   if(method==='POST'&&(/\/messages$|\/approve$|\/reply$|\/research|\/write-|\/execute$/.test(path))){forbidden++;return route.abort();}
   return route.continue();
  });
  await page.goto(base);await loginFixture(page);
  for(const variant of ['success','failure']){
   scenario=variant;const before={creates,routes,submissions};
   if(variant==='failure')await page.locator('.sidebar button.new').click();
   if(await getSystemMode(page))throw Error('Explicit system control is enabled before automatic read');
   await page.locator('.composer textarea').fill(goal);
   await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
   await page.locator('.message.assistant').getByText(variant==='success'?success:failure,{exact:true}).waitFor();
   const panel=page.getByRole('region',{name:'Details Abarbeitung',exact:true});
   await panel.locator('.agent-work-summary').getByText(variant==='success'?/Abfrage abgeschlossen/:/Angehalten/).waitFor();
   if(creates-before.creates!==1||routes-before.routes!==1||submissions-before.submissions!==1||forbidden)throw Error('Read required extra confirmation/submission or normal LLM request');
   if(await page.getByRole('button',{name:/freigeben und fortsetzen|Tatsächlichen Zustand nur lesend prüfen/}).count())throw Error('Read-only access check exposes write approval or uncertain recovery');
   await panel.locator('summary').first().click();await panel.locator('details[data-agent-job] > summary').click();
   await panel.getByText('Schritt 1: Freigegebene Verbindung ausschließlich lesend prüfen · '+(variant==='success'?'abgeschlossen':'fehlgeschlagen'),{exact:true}).waitFor();
   await panel.getByText('Aufruf und Beleg',{exact:true}).click();await panel.locator('pre').filter({hasText:'"tool": "http"'}).waitFor();
   const trace=await panel.locator('pre').filter({hasText:'"tool": "http"'}).innerText();
   if(!trace.includes('"GET"')||!trace.includes('"/api/"')||trace.includes('ha.websocket')||trace.includes('config/verify_connection'))throw Error('Trace is not fixed read-only HTTP GET /api/');
   if(variant==='success'){
    await panel.locator('summary').first().click();await page.locator('.chat-scroll').evaluate(e=>{e.scrollTop=0;});await page.locator('.message.user').getByText(goal,{exact:true}).waitFor();await page.evaluate(()=>document.activeElement?.blur());
    await page.screenshot({path:fileURLToPath(new URL('../.local/browser/ha-access-ui.png',import.meta.url)),fullPage:true});
   }
   for(const width of [1366,320]){
    await page.setViewportSize({width,height:1050});await pause(100);
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('HA access chat overflows mobile viewport');
   }
   await page.setViewportSize({width:1366,height:1050});
  }
  if(errors.length)throw Error('Page errors: '+errors.join(';'));
  console.log('HA access UI passed: automatic integration routing with system control off, one new chat/submission per request, observed success and clear failed summary, read-only GET /api/ trace, no confirmation/effect/research/ordinary LLM request, desktop/mobile. Routing and HA responses are synthetic; no live Home Assistant calls.');
 }finally{await browser.close();}
}
