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
 await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',error=>reject(Error('HA read recovery fixture port18767 unavailable ('+error.code+'); existing service untouched')));probe.listen(18767,'127.0.0.1',()=>probe.close(resolve));});
 folder=await realpath(await mkdtemp(join(tmpdir(),'obdaai-ha-read-recovery-ui-')));
 const root=fileURLToPath(new URL('../',import.meta.url));
 const python=process.env.HUB_TEST_PYTHON?resolve(process.env.HUB_TEST_PYTHON):fileURLToPath(new URL('../.venv/bin/python',import.meta.url));
 server=spawn(python,['-m','uvicorn','scripts.browser_fixture:app','--host','127.0.0.1','--port','18767'],{cwd:root,env:{...process.env,HUB_BROWSER_FIXTURE_DIR:folder,HUB_BROWSER_ORIGIN:base},stdio:['ignore','pipe','pipe']});
 serverExit=new Promise(resolve=>server.once('close',resolve));server.once('error',e=>{startError=e;});
 for(const stream of [server.stdout,server.stderr])stream.on('data',chunk=>{serverLog=(serverLog+chunk.toString()).slice(-6000);});
 process.once('exit',stop);process.once('SIGINT',interrupt);process.once('SIGTERM',terminate);
 const deadline=Date.now()+30000;let healthy=false;
 while(Date.now()<deadline){if(startError)throw startError;if(server.exitCode!==null||server.signalCode)throw Error('Owned fixture stopped: '+serverLog);try{healthy=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok;}catch{}if(healthy)break;await pause(100);}
 if(!healthy)throw Error('Owned HA read recovery fixture startup timed out: '+serverLog);
 await checks();
}finally{
 if(server){stop();let timer;try{await Promise.race([serverExit,new Promise(resolve=>{timer=setTimeout(resolve,5000);})]);}finally{clearTimeout(timer);}if(server.pid&&server.exitCode===null&&!server.signalCode){server.kill('SIGKILL');await serverExit;}}
 process.removeListener('exit',stop);process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',terminate);
 if(folder)await rm(folder,{recursive:true,force:true});
}
async function checks(){
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1366,height:1050}}),errors=[];
 page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
 const iid='639e1634-575f-436b-ae9a-cbb19eb0ff9a',goal='welche lampen habe ich in home assistant';
 const summary='Zwei Lampen: Aurora Wohnzimmer ist an, Aurora Küche ist aus.';
 const projection={items_path:'',where_pointer:'/entity_id',where_equals:null,where_prefix:'light.',fields:['/entity_id','/state','/attributes/friendly_name'],limit:100};
 const args=(path,selection=null)=>({method:'GET',path,query:{},body:null,projection:selection,verification:null});
 const decision=(path,selection=null)=>({kind:'tool',integration_id:iid,tool:'http',arguments:args(path,selection),message:path==='/api/states'?'Lampen lesen':'Freigegebenen Status lesen'});
 const modelIds=Array.from({length:3},()=>crypto.randomUUID());
 const model=(sequence,index,result)=>({sequence,kind:'model',status:'succeeded',sha256:'a'.repeat(64),approved:false,model_run_id:modelIds[index],document:{instruction_sha256:'b'.repeat(64)},result});
 const read=(sequence,document,status,result)=>({sequence,kind:'read',status,sha256:'c'.repeat(64),approved:false,model_run_id:null,document,result});
 const steps=[
  read(1,{...decision('/api/'),capability_inspection:true,message:'Freigegebene Verbindung ausschließlich lesend prüfen'},'succeeded',{http_status:200,body:{message:'API running.'},effect_verified:false}),
  model(2,0,decision('/api/light')),
  read(3,decision('/api/light'),'failed',{failure_category:'not_found',http_status:404,automatic_retry:false,effect_verified:false}),
  model(4,1,decision('/api/states',projection)),
  read(5,decision('/api/states',projection),'succeeded',{http_status:200,effect_verified:false,body:{items:[{'/entity_id':'light.synthetic_living','/state':'on','/attributes/friendly_name':'Aurora Wohnzimmer'},{'/entity_id':'light.synthetic_kitchen','/state':'off','/attributes/friendly_name':'Aurora Küche'}],matched:2,returned:2}}),
  model(6,2,{kind:'finish',message:summary}),
 ];
 let chat=null,job=null,creates=0,routes=0,submissions=0,forbidden=0,receipts=[];
 const json=(route,body)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
 try{
  await page.route(base+'/api/**',async route=>{
   const r=route.request(),u=new URL(r.url()),path=u.pathname,method=r.method();
   if(path==='/api/integrations'&&method==='GET')return json(route,{integrations:[{id:iid,name:'Home Assistant Aurora',kind:'home_assistant',revision:1,enabled:true,writes_enabled:false,secret_saved:true,execution_available:true,config:{}}]});
   if(path.startsWith('/api/integration-bindings/conversation/')&&method==='GET')return json(route,{revision:0,selection_mode:'automatic',effective_selection_mode:'automatic',integration_ids:[],effective_integration_ids:[iid],execution_available:true});
   if(path==='/api/conversations'&&method==='POST')creates++;
   if(path.endsWith('/integration-route')&&method==='POST'){routes++;if(r.postDataJSON().goal!==goal)throw Error('Routing lost exact lamp request');return json(route,{route:'agent',integration_ids:[iid]});}
   if(/^\/api\/conversations\/[^/]+\/agent-runs$/.test(path)&&method==='POST'){
    submissions++;const body=r.postDataJSON();if(body.goal!==goal||!body.request_id||JSON.stringify(body.integration_ids)!==JSON.stringify([iid]))throw Error('Lamp request identity/target missing');
    chat=path.split('/')[3];job={id:crypto.randomUUID(),conversation_id:chat,goal,status:'observed',summary,cancel_requested:false,automatic_retry:false,label:'LOCAL_ONLY',steps};return json(route,job);
   }
   if(path==='/api/agent-runs'&&method==='GET')return json(route,job&&u.searchParams.get('conversation_id')===chat?[job]:[]);
   const receipt=path.match(/^\/api\/agent-runs\/([^/]+)\/steps\/(\d+)$/);
   if(receipt&&method==='GET'){
    if(receipt[1]!==job?.id)throw Error('Wrong job receipt');const step=steps.find(s=>s.sequence===Number(receipt[2]));if(!step)throw Error('Unknown receipt');receipts.push(step.sequence);return json(route,{document:step.document,result:step.result,sha256:step.sha256,label:'LOCAL_ONLY'});
   }
   if(/^\/api\/conversations\/[^/]+$/.test(path)&&method==='GET'){
    const response=await route.fetch(),detail=await response.json();
    if(path.split('/')[3]===chat&&job)detail.messages=[...detail.messages,{id:crypto.randomUUID(),role:'user',content:goal,label:'LOCAL_ONLY',revision:1,processing:null},{id:crypto.randomUUID(),role:'assistant',content:summary,label:'LOCAL_ONLY',revision:1,processing:{run_id:modelIds[2],provider:'local',model:'synthetic-local-model',model_used:true,status:'succeeded',agent_job_id:job.id}}];
    return json(route,detail);
   }
   if(method==='POST'&&(/\/messages$|\/approve$|\/reply$|\/research|\/write-|\/execute$/.test(path))){forbidden++;return route.abort();}
   return route.continue();
  });
  await page.goto(base);await loginFixture(page);
  if(await page.getByLabel('Systeme steuern',{exact:true}).isChecked())throw Error('Explicit administration enabled before automatic read');
  await page.locator('.composer textarea').fill(goal);await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
  await page.locator('.message.assistant').getByText(summary,{exact:true}).waitFor();
  const panel=page.getByRole('region',{name:'Details Abarbeitung',exact:true});await panel.locator('summary').first().filter({hasText:'Nur lesende Schritte abgeschlossen'}).waitFor();
  if(creates!==1||routes!==1||submissions!==1||forbidden)throw Error('Read recovery required extra submission or ordinary LLM request');
  if(await page.getByRole('button',{name:/freigeben und fortsetzen|Tatsächlichen Zustand nur lesend prüfen/}).count())throw Error('Recovered read exposed approval/reconciliation');
  await panel.locator('summary').first().click();await panel.locator('details[data-agent-job] > summary').click();const articles=panel.locator('article');if(await articles.count()!==3)throw Error('Read trace omitted failure or included model as action');
  const expected=[{path:'/api/',status:'succeeded',code:200},{path:'/api/light',status:'failed',code:404},{path:'/api/states',status:'succeeded',code:200}];
  for(let i=0;i<3;i++){
   const article=articles.nth(i);await article.getByText('Aufruf und Beleg',{exact:true}).click();await article.locator('pre').filter({hasText:expected[i].path}).waitFor();const proof=JSON.parse(await article.locator('pre').innerText());
   if(proof.document.tool!=='http'||proof.document.arguments.method!=='GET'||proof.document.arguments.path!==expected[i].path||proof.result.http_status!==expected[i].code)throw Error('Read receipt shape/path/status changed');
   if(i===1&&!await article.getByText(/fehlgeschlagen/).count())throw Error('404 evidence silently became successful');
   if(i===2&&(proof.document.arguments.projection.where_prefix!=='light.'||proof.result.body.matched!==2||proof.result.body.items.some(x=>!x['/entity_id'].startsWith('light.'))))throw Error('Lamp projection omitted or wrong domain');
   await article.getByText('Aufruf und Beleg',{exact:true}).click();
  }
  if(receipts.join(',')!=='1,3,5')throw Error('Wrong receipt requests');
  await panel.locator('summary').first().click();await page.locator('.chat-scroll').evaluate(e=>{e.scrollTop=0;});await page.locator('.message.user').getByText(goal,{exact:true}).waitFor();
  await page.screenshot({path:resolve('.local/browser/ha-read-recovery-ui.png'),fullPage:true});
  for(const width of [1366,320]){await page.setViewportSize({width,height:1050});await pause(100);if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Lamp recovery chat overflow');}
  if(errors.length)throw Error(errors.join(';'));
  console.log('HA read recovery UI passed: automatic route with system control off, one submission, two synthetic lamps/states, preserved failed GET /api/light 404, successful GET /api/states with local light projection, final local-model provenance, no confirmation/effect/ask, 320px/desktop. Integration routing, model and HA responses mocked; no live HA dispatch.');
 }finally{await browser.close();}
}
