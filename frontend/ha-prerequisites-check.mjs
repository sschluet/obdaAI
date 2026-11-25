import {isDeepStrictEqual} from 'node:util';
import './agent-prerequisites-check.mjs';
// Real React/auth/conversation APIs on a fresh isolated synthetic fixture.
// Agent jobs and displayed messages are synthetic stubs; no live targets or model calls.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,realpath,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:net';
const base='http://127.0.0.1:18843',pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let server,serverExit,folder,serverLog='',startError;
const stop=()=>{if(server?.pid&&server.exitCode===null&&!server.signalCode)server.kill('SIGTERM')};
const interrupt=()=>{stop();process.exit(130)},terminate=()=>{stop();process.exit(143)};
try{
 await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',error=>reject(Error('HA prerequisites fixture port18843 unavailable ('+error.code+'); existing service untouched')));probe.listen(18843,'127.0.0.1',()=>probe.close(resolve));});
 folder=await realpath(await mkdtemp(join(tmpdir(),'obdaai-ha-prerequisites-')));
 const root=fileURLToPath(new URL('../',import.meta.url));
 const python=process.env.HUB_TEST_PYTHON?resolve(process.env.HUB_TEST_PYTHON):fileURLToPath(new URL('../.venv/bin/python',import.meta.url));
 server=spawn(python,['-m','uvicorn','scripts.browser_fixture:app','--host','127.0.0.1','--port','18843'],{cwd:root,env:{...process.env,HUB_BROWSER_FIXTURE_DIR:folder,HUB_BROWSER_ORIGIN:base},stdio:['ignore','pipe','pipe']});
 serverExit=new Promise(resolve=>server.once('close',resolve));server.once('error',e=>{startError=e;});
 for(const stream of [server.stdout,server.stderr])stream.on('data',chunk=>{serverLog=(serverLog+chunk.toString()).slice(-6000);});
 process.once('exit',stop);process.once('SIGINT',interrupt);process.once('SIGTERM',terminate);
 const deadline=Date.now()+30000;let healthy=false;
 while(Date.now()<deadline){if(startError)throw startError;if(server.exitCode!==null||server.signalCode)throw Error('Owned fixture stopped: '+serverLog);try{healthy=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok;}catch{}if(healthy)break;await pause(100);}
 if(!healthy)throw Error('Owned HA prerequisites fixture startup timed out: '+serverLog);
 await checks();
}finally{
 if(server){stop();let timer;try{await Promise.race([serverExit,new Promise(resolve=>{timer=setTimeout(resolve,5000);})]);}finally{clearTimeout(timer);}if(server.pid&&server.exitCode===null&&!server.signalCode){server.kill('SIGKILL');await serverExit;}}
 process.removeListener('exit',stop);process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',terminate);
 if(folder)await rm(folder,{recursive:true,force:true});
}
async function checks(){
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[],requests=[],external=[];page.setDefaultTimeout(20000);page.on('pageerror',error=>errors.push(error.message));
 try{
 await page.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():(external.push(true),route.abort()));
 await page.goto(base);await page.getByLabel('Passwort',{exact:true}).fill('synthetic-ui-password');const login=page.waitForResponse(r=>r.url()===base+'/api/login'&&r.request().method()==='POST');await page.getByRole('button',{name:'Anmelden',exact:true}).click();const auth=await(await login).json(),headers={'X-CSRF-Token':auth.csrf,Origin:base};await page.getByRole('button',{name:'Abmelden',exact:true}).waitFor();
 const call=async(path,method='GET',data)=>{const response=await page.request.fetch(base+'/api'+path,{method,headers,...(data===undefined?{}:{data})});if(!response.ok())throw Error('Synthetic prerequisite setup '+method+' '+response.status());return response.json()};
 let profile=await call('/integrations','POST',{name:'Aurora · HA-Sicherungsregel',kind:'home_assistant',url:'https://ha.example.test',auth:'api_key',secret:'synthetic-ha-ui-token'});profile=await call('/integrations/'+profile.id+'/control','PATCH',{expected_revision:profile.revision,enabled:true});
 const policyPath='/integrations/'+profile.id+'/agent-policy';let policy=await call(policyPath);
 if((policy.rules.effect_prerequisites??[]).length)throw Error('New policy does not default to empty prerequisites');
 await page.goto(base+'/?view=Einstellungen&settingsTab=Integrationen');const defaultRow=page.locator('.registry-table tr').filter({hasText:profile.name});await defaultRow.getByRole('button',{name:'KI-Zugriff',exact:true}).click();const defaultEditor=page.getByRole('region',{name:'KI-Zugriff für '+profile.name,exact:true});await defaultEditor.locator('summary').filter({hasText:'Erweiterte Berechtigungen'}).click();const defaultRule=defaultEditor.getByRole('checkbox',{name:'Backup vor dem Update-Dienst',exact:true});if(await defaultRule.isChecked()||!await defaultRule.isDisabled())throw Error('Default prerequisite is enabled or invents missing API permissions');await defaultEditor.getByText('Erlaube zuerst die Update- und Sicherungsaktionen in den API-Berechtigungen: POST und passende API-Pfade für beide Aktionen.',{exact:true}).waitFor();await defaultEditor.getByRole('button',{name:'Schließen',exact:true}).click();

 const foreign={operation:{tool:'http',method:'POST',path:'/api/services/script/turn_on'},requires:{tool:'http',method:'POST',path:'/api/services/backup/create'}};
 const known={operation:{tool:'http',method:'POST',path:'/api/services/update/install'},requires:{tool:'http',method:'POST',path:'/api/services/backup/create_automatic'}};
 policy=await call(policyPath,'PUT',{expected_revision:policy.revision,expected_profile_revision:profile.revision,rules:{...policy.rules,enabled:true,autonomous:false,max_effects:0,http_methods:['GET','POST'],http_prefixes:['/api/'],effect_prerequisites:[foreign]}});
 const saved=async()=>call(policyPath),equal=(a,b)=>isDeepStrictEqual(a,b);
 page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/')&&!['GET','HEAD'].includes(request.method()))requests.push({path:url.pathname,method:request.method(),body:request.postDataJSON()})});
 await page.goto(base+'/?view=Einstellungen&settingsTab=Integrationen');const row=page.locator('.registry-table tr').filter({hasText:profile.name});
 const editor=page.getByRole('region',{name:'KI-Zugriff für '+profile.name,exact:true}),checkbox=editor.getByRole('checkbox',{name:'Backup vor dem Update-Dienst',exact:true});
 const open=async()=>{await row.getByRole('button',{name:'KI-Zugriff',exact:true}).click();await editor.locator('summary').filter({hasText:'Erweiterte Berechtigungen'}).click();await checkbox.waitFor()};
 const save=async()=>{await editor.getByRole('button',{name:'Zugriff speichern',exact:true}).click();await editor.waitFor({state:'hidden'})};
 await open();if(await checkbox.isChecked())throw Error('Optional backup rule enabled by default');await checkbox.check();await save();policy=await saved();if(!equal(policy.rules.effect_prerequisites,[foreign,known])||policy.writes_enabled||policy.rules.autonomous||policy.rules.production_ha_approved)throw Error('Read-only prerequisite save lost custom rule or granted authority');if(requests.some(r=>r.path.endsWith('/write-control')))throw Error('Checkbox silently changed write authority');
 await open();if(!await checkbox.isChecked())throw Error('Saved backup prerequisite lost on reopen');await checkbox.uncheck();await editor.getByLabel('Maximale Werkzeugschritte',{exact:true}).fill('21');await save();policy=await saved();if(!equal(policy.rules.effect_prerequisites,[foreign])||policy.rules.max_steps!==21)throw Error('Uncheck replaced foreign prerequisites or unrelated edit');
 // A concurrent policy revision must retain the local draft and not replay a save.
 await open();await checkbox.check();const original=await saved();await call(policyPath,'PUT',{expected_revision:original.revision,expected_profile_revision:original.profile_revision,rules:{...original.rules,max_steps:33}});const beforeConflict=requests.length;await editor.getByRole('button',{name:'Zugriff speichern',exact:true}).click();await editor.getByRole('alert').waitFor();if(!await checkbox.isChecked()||requests.length!==beforeConflict+1||(await saved()).rules.effect_prerequisites.length!==1)throw Error('Stale policy save discarded draft or retried/granted');
 await editor.getByRole('button',{name:'Schließen',exact:true}).click();const discard=page.getByRole('dialog',{name:'Ungespeicherte Änderungen',exact:true});await discard.getByRole('button',{name:'Weiter bearbeiten',exact:true}).click();if(!await checkbox.isChecked())throw Error('Cancelled discard loses rule draft');await editor.getByRole('button',{name:'Schließen',exact:true}).click();await discard.getByRole('button',{name:'Ohne Speichern weiter',exact:true}).click();await editor.waitFor({state:'hidden'});
 // Existing autonomous policy remains autonomous; configuring the rule grants nothing extra.
 profile={...profile,...await call('/integrations/'+profile.id+'/write-control','PATCH',{expected_revision:policy.profile_revision,writes_enabled:true})};policy=await saved();await call(policyPath,'PUT',{expected_revision:policy.revision,expected_profile_revision:profile.revision,rules:{...policy.rules,autonomous:true,max_effects:5,http_methods:['GET','POST']}});
 await page.reload();await open();await checkbox.check();await save();policy=await saved();if(!policy.writes_enabled||!policy.rules.autonomous||policy.rules.production_ha_approved||!equal(policy.rules.effect_prerequisites,[foreign,known]))throw Error('Prerequisite changed existing autonomy/custom/production rules');
 await open();await editor.getByRole('radio',{name:'Nur lesen',exact:true}).check();if(!await checkbox.isChecked())throw Error('Changing access discards prerequisite');await save();policy=await saved();if(policy.writes_enabled||policy.rules.autonomous||!equal(policy.rules.effect_prerequisites,[foreign,known]))throw Error('Read-only access toggle grants writes or loses custom safeguard');const controls=requests.filter(r=>r.path.endsWith('/write-control'));if(controls.length!==1||controls[0].body.writes_enabled!==false)throw Error('Prerequisite altered authority outside explicit read-only selection');
 // A previously explicit basic-backup rule remains exact, without adding a second automatic rule.
 const basic={...known,requires:{...known.requires,path:'/api/services/backup/create'}};
 await call(policyPath,'PUT',{expected_revision:policy.revision,expected_profile_revision:policy.profile_revision,rules:{...policy.rules,effect_prerequisites:[foreign,basic]}});
 await page.reload();await open();if(!await checkbox.isChecked())throw Error('Existing basic backup rule was not recognized');await editor.getByText('Gespeicherte Backup-Methode: backup.create. Sie bleibt beim Bearbeiten erhalten.',{exact:true}).waitFor();await checkbox.uncheck();await checkbox.check();await save();policy=await saved();if(!equal(policy.rules.effect_prerequisites,[foreign,basic]))throw Error('Editing existing basic rule silently added/replaced automatic backup');
 await page.setViewportSize({width:320,height:900});await open();await checkbox.scrollIntoViewIfNeeded();if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Prerequisite mobile overflow');await checkbox.uncheck();await checkbox.check();if(!await checkbox.isChecked())throw Error('Mobile checkbox inaccessible');
 const unexpected=requests.filter(r=>!(r.path==='/api'+policyPath&&r.method==='PUT'||r.path==='/api/integrations/'+profile.id+'/write-control'&&r.method==='PATCH'));if(unexpected.length||external.length||errors.length)throw Error('Unexpected target/model/network or UI error '+JSON.stringify({unexpected:unexpected.map(({path,method})=>({path,method})),external_count:external.length,errors}));
 console.log('HA prerequisite UI passed: optional off default, real policy save/reopen, exact custom-rule preservation, CAS conflict/draft/discard, existing autonomy unchanged, explicit read-only access preserved, automatic backup default and exact basic-rule restoration, mobile320. No real model, HA or other target access.');
 }finally{await browser.close()}
}
