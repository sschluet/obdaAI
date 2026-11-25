// Real React/auth/conversation APIs on a fresh isolated synthetic fixture.
// Agent jobs and displayed messages are synthetic stubs; no live targets or model calls.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,realpath,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:net';
const base='http://127.0.0.1:18837',pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let server,serverExit,folder,serverLog='',startError;
const stop=()=>{if(server?.pid&&server.exitCode===null&&!server.signalCode)server.kill('SIGTERM')};
const interrupt=()=>{stop();process.exit(130)},terminate=()=>{stop();process.exit(143)};
try{
 await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',error=>reject(Error('Chat title activity fixture port18837 unavailable ('+error.code+'); existing service untouched')));probe.listen(18837,'127.0.0.1',()=>probe.close(resolve));});
 folder=await realpath(await mkdtemp(join(tmpdir(),'obdaai-chat-title-activity-')));
 const root=fileURLToPath(new URL('../',import.meta.url));
 const python=process.env.HUB_TEST_PYTHON?resolve(process.env.HUB_TEST_PYTHON):fileURLToPath(new URL('../.venv/bin/python',import.meta.url));
 server=spawn(python,['-m','uvicorn','scripts.browser_fixture:app','--host','127.0.0.1','--port','18837'],{cwd:root,env:{...process.env,HUB_BROWSER_FIXTURE_DIR:folder,HUB_BROWSER_ORIGIN:base},stdio:['ignore','pipe','pipe']});
 serverExit=new Promise(resolve=>server.once('close',resolve));server.once('error',e=>{startError=e;});
 for(const stream of [server.stdout,server.stderr])stream.on('data',chunk=>{serverLog=(serverLog+chunk.toString()).slice(-6000);});
 process.once('exit',stop);process.once('SIGINT',interrupt);process.once('SIGTERM',terminate);
 const deadline=Date.now()+30000;let healthy=false;
 while(Date.now()<deadline){if(startError)throw startError;if(server.exitCode!==null||server.signalCode)throw Error('Owned fixture stopped: '+serverLog);try{healthy=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok;}catch{}if(healthy)break;await pause(100);}
 if(!healthy)throw Error('Owned Chat title activity fixture startup timed out: '+serverLog);
 await checks();
}finally{
 if(server){stop();let timer;try{await Promise.race([serverExit,new Promise(resolve=>{timer=setTimeout(resolve,5000);})]);}finally{clearTimeout(timer);}if(server.pid&&server.exitCode===null&&!server.signalCode){server.kill('SIGKILL');await serverExit;}}
 process.removeListener('exit',stop);process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',terminate);
 if(folder)await rm(folder,{recursive:true,force:true});
}
async function checks(){
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.setDefaultTimeout(20000);page.on('pageerror',error=>errors.push(error.message));
 try{
 await page.goto(base);await page.getByLabel('Passwort',{exact:true}).fill('synthetic-ui-password');const login=page.waitForResponse(r=>r.url()===base+'/api/login'&&r.request().method()==='POST');await page.getByRole('button',{name:'Anmelden',exact:true}).click();const auth=await(await login).json();await page.getByRole('button',{name:'Navigation öffnen',exact:true}).waitFor();
 await page.getByRole('button',{name:'Modellwahl',exact:true}).click();await page.getByRole('menuitemradio',{name:'Nur lokal',exact:true}).click();
 let routeMode,posts=0;await page.route(base+'/api/conversations/*/integration-route',async route=>{routeMode=route.request().postDataJSON().model_mode;await route.continue()});page.on('request',request=>{if(request.method()==='POST'&&new URL(request.url()).pathname.endsWith('/messages'))posts++});
 const created=page.waitForResponse(r=>r.url()===base+'/api/conversations'&&r.request().method()==='POST'&&r.ok());
 await page.getByLabel('Nachricht',{exact:true}).fill('Analyse eines synthetischen Umzugsplans. SYNTHETIC_LONG_STREAM_RESPONSE');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();const chat=await(await created).json();
 let detail;const firstDeadline=Date.now()+10000;do{detail=await(await page.request.get(base+'/api/conversations/'+chat.id)).json();if(detail.runs.length)break;await pause(100)}while(Date.now()<firstDeadline);
 if(!detail.runs.length||!detail.title.trim()||detail.title==='Neues Gespräch')throw Error('Initial accepted request lacks immediate meaningful title');
 await page.locator('.chat-top .context').filter({hasText:detail.title}).waitFor();await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();await page.locator('.history').getByRole('button',{name:detail.title,exact:true}).waitFor();await page.getByRole('button',{name:'Navigation schließen',exact:true}).click();
 if(!detail.runs.some(run=>['queued','routing','streaming'].includes(run.status)))throw Error('Initial title was only observed after completed generation');
 const titleDeadline=Date.now()+10000;do{detail=await(await page.request.get(base+'/api/conversations/'+chat.id)).json();if(!['queued','running'].includes(detail.title_status))break;await pause(100)}while(Date.now()<titleDeadline);
 await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).click();await page.getByRole('button',{name:'Nachricht senden',exact:true}).waitFor();
 const doneDeadline=Date.now()+10000;do{detail=await(await page.request.get(base+'/api/conversations/'+chat.id)).json();if(detail.runs.every(run=>!['queued','routing','streaming'].includes(run.status)))break;await pause(100)}while(Date.now()<doneDeadline);
 if(detail.runs.length!==1||!['cancelled','interrupted'].includes(detail.runs[0].status))throw Error('Owned ordinary request did not retain its termination receipt');
 await page.locator('.chat-top .context').filter({hasText:detail.title}).waitFor();await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();await page.locator('.history').getByRole('button',{name:detail.title,exact:true}).waitFor();await page.getByRole('button',{name:'Navigation schließen',exact:true}).click();
 await page.reload();await page.locator('.chat-top .context').filter({hasText:detail.title}).waitFor();if(posts!==1||routeMode!=='local'||errors.length)throw Error('Title refresh replayed request, lost mode or raised page errors');
 console.log('Chat title activity passed: real synthetic API titles are visible in header/sidebar while the first ordinary response still streams; explicit cancellation retains one durable terminated run and refreshes title metadata across header/sidebar/reload. Model mode local is forwarded; no live model or target calls.');
 }finally{await browser.close()}
}
