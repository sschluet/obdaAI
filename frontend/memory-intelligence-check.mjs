import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:net';
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const base=process.env.MEMORY_FIXTURE_URL||'http://127.0.0.1:18769';
if(!['http://127.0.0.1:18765','http://127.0.0.1:18767','http://127.0.0.1:18769'].includes(base))throw Error('Only isolated synthetic fixtures are permitted');
// The default check owns an entirely fresh fixture, independently of the parent suite.
// A supplied MEMORY_FIXTURE_URL remains supported for dedicated manual fixtures.
let server,serverExit,folder,startError,serverLog='';
const killOwned=()=>{if(server?.pid&&server.exitCode===null&&!server.signalCode)server.kill('SIGTERM')};
const onInterrupt=()=>{killOwned();process.exit(130)},onTerminate=()=>{killOwned();process.exit(143)};
try{
 if(!process.env.MEMORY_FIXTURE_URL){
  // Never adopt or stop another suite's listener on the dedicated port.
  await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',()=>reject(Error('Memory fixture port 18769 is already in use; no existing service was changed')));probe.listen(18769,'127.0.0.1',()=>probe.close(resolve))});
  folder=await mkdtemp(join(tmpdir(),'obdaai-memory-ui-'));
  const root=fileURLToPath(new URL('../',import.meta.url));
  const python=process.env.HUB_TEST_PYTHON?resolve(process.env.HUB_TEST_PYTHON):fileURLToPath(new URL('../.venv/bin/python',import.meta.url));
  server=spawn(python,['-m','uvicorn','scripts.browser_fixture:app','--host','127.0.0.1','--port','18769'],{cwd:root,env:{...process.env,HUB_BROWSER_FIXTURE_DIR:folder,HUB_BROWSER_ORIGIN:base,HUB_MEMORY_UI_FIXTURE:'1'},stdio:['ignore','pipe','pipe']});
  serverExit=new Promise(resolve=>server.once('close',resolve));server.once('error',error=>{startError=error});
  for(const stream of [server.stdout,server.stderr])stream.on('data',chunk=>{serverLog=(serverLog+chunk.toString()).slice(-6000)});
  process.once('exit',killOwned);process.once('SIGINT',onInterrupt);process.once('SIGTERM',onTerminate);
  const deadline=Date.now()+30000;let healthy=false;
  while(Date.now()<deadline){
   if(startError)throw startError;
   if(server.exitCode!==null||server.signalCode)throw Error('Synthetic memory fixture exited during startup: '+serverLog);
   try{healthy=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok}catch{}
   if(healthy)break;
   await pause(100);
  }
  if(!healthy)throw Error('Synthetic memory fixture did not become healthy: '+serverLog);
 }
 await runMemoryChecks();
}finally{
 if(server){killOwned();let timer;try{await Promise.race([serverExit,new Promise(resolve=>{timer=setTimeout(resolve,5000)})])}finally{clearTimeout(timer)}if(server.pid&&server.exitCode===null&&!server.signalCode){server.kill('SIGKILL');await serverExit}}
 process.removeListener('exit',killOwned);process.removeListener('SIGINT',onInterrupt);process.removeListener('SIGTERM',onTerminate);
 if(folder)await rm(folder,{recursive:true,force:true});
}
async function runMemoryChecks(){
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1280,height:950}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(15000);
try{
 await page.goto(base);const auth=await loginFixture(page),headers={'X-CSRF-Token':auth.csrf,Origin:base};
 await page.getByRole('button',{name:'Wissen',exact:true}).click();await page.getByRole('tab',{name:'Persönliche Merkliste',exact:true}).click();
 const panel=page.getByRole('region',{name:'Gedächtnis',exact:true}),candidates=panel.getByRole('region',{name:'Vorschläge prüfen',exact:true});await candidates.getByText('Keine Vorschläge zur Prüfung.',{exact:true}).or(candidates.getByText('Synthetic sensitive preference: I prefer quiet mornings.',{exact:true})).first().waitFor();
 if(await panel.getByLabel('Speicherort',{exact:true}).inputValue()!=='app')throw Error('New memory is not app-owned by default');
 const fresh=candidates.locator('article').filter({hasText:'Synthetic sensitive preference:'}),stale=candidates.locator('article').filter({hasText:'Die Quelle wurde geändert oder entfernt.'});
 await fresh.waitFor();const denied=await page.request.post(base+'/api/memory-candidates/2f31a0a4-37ef-4e09-bc52-71025a2ca901/review',{headers,data:{expected_revision:1,decision:'approve'}});if(denied.status()!==409)throw Error('Changed source approval was not rejected at API');const anonymous=await browser.newContext();try{if((await anonymous.request.get(base+'/api/memory-settings')).status()!==401)throw Error('Memory settings available without login')}finally{await anonymous.close()}if(!await stale.getByRole('button',{name:'Merken',exact:true}).isDisabled())throw Error('Changed source can still be approved');
 await fresh.getByRole('button',{name:'Merken',exact:true}).click();await panel.getByText('Vorschlag ins Gedächtnis übernommen.',{exact:true}).waitFor();
 await stale.getByRole('button',{name:'Verwerfen',exact:true}).click();await candidates.getByText('Keine Vorschläge zur Prüfung.',{exact:true}).waitFor();
 await panel.getByLabel('Titel',{exact:true}).fill('Synthetic durable memory');await panel.getByLabel('Memory-Inhalt',{exact:true}).fill('Synthetic fact retained independently of provider.');
 await panel.getByRole('button',{name:'Erinnerung speichern',exact:true}).click();await panel.getByText('Erinnerung gespeichert. Sie gehört deinem obdaAI-Gedächtnis.',{exact:true}).waitFor();
 let listing=await(await page.request.get(base+'/api/memories')).json(),row=listing.find(r=>r.content.includes('Synthetic fact retained'));if(!row||row.storage!=='app'||row.cloud_providers.length)throw Error('Memory persistence/default privacy failed');
 await panel.getByLabel('Memory-Inhalt',{exact:true}).fill('Synthetic unsaved edit');await panel.getByLabel('Memory durchsuchen',{exact:true}).fill('no-synthetic-match');if(await panel.getByLabel('Memory-Inhalt',{exact:true}).inputValue()!=='Synthetic unsaved edit')throw Error('Search discarded editor draft');
 await panel.getByRole('button',{name:'Neues Memory',exact:true}).click();await page.getByRole('dialog',{name:'Ungespeicherte Erinnerung',exact:true}).waitFor();await page.keyboard.press('Escape');if(await panel.getByLabel('Memory-Inhalt',{exact:true}).inputValue()!=='Synthetic unsaved edit')throw Error('Escape discarded draft');
 const concurrent=await page.request.patch(base+'/api/memories/'+row.id,{headers,data:{id:row.id,title:'Synthetic durable memory',content:'Synthetic concurrent fact',project_id:null,revision:row.revision,storage:'app',category:'personal',fact_type:'fact',sensitivity:'private',cloud_providers:[]}});if(!concurrent.ok())throw Error('Concurrent synthetic update failed');
 await panel.getByRole('button',{name:'Erinnerung speichern',exact:true}).click();await panel.getByRole('alert').waitFor();if(await panel.getByLabel('Memory-Inhalt',{exact:true}).inputValue()!=='Synthetic unsaved edit')throw Error('CAS discarded draft');
 await panel.getByRole('button',{name:'Verglichen · meinen Entwurf behalten',exact:true}).click();await panel.getByRole('button',{name:'Erinnerung speichern',exact:true}).click();await panel.getByText('Erinnerung gespeichert. Sie gehört deinem obdaAI-Gedächtnis.',{exact:true}).waitFor();
 await panel.getByRole('button',{name:'Aus Gedächtnis entfernen',exact:true}).click();const remove=page.getByRole('dialog',{name:'Erinnerung entfernen',exact:true});await remove.getByText(/Ursprüngliche Chats werden dadurch nicht gelöscht/).waitFor();await page.keyboard.press('Escape');if(!await panel.getByRole('button',{name:'Aus Gedächtnis entfernen',exact:true}).isVisible())throw Error('Cancelled forget lost selected record');
 await panel.getByRole('button',{name:'Aus Gedächtnis entfernen',exact:true}).click();await remove.getByRole('button',{name:'Jetzt entfernen',exact:true}).click();await panel.getByText('Aus dem Gedächtnis entfernt. Ursprüngliche Chats bleiben erhalten.',{exact:true}).waitFor();
 const forgotten=await(await page.request.get(base+'/api/memories?status=forgotten&deleted=true')).json();if(!forgotten.some(r=>r.id===row.id&&!r.content))throw Error('Forgotten native memory remains recoverable through content API');
 await panel.getByText('So lernt dein Gedächtnis',{exact:true}).click();const locals=(await(await page.request.get(base+'/api/providers')).json()).providers.filter(provider=>provider.kind==='local'&&provider.enabled&&provider.model);const modelChoice=panel.getByLabel('Modell zum Lernen',{exact:true});await modelChoice.waitFor();if(!locals.length)throw Error('Synthetic local provider unavailable');await modelChoice.selectOption(locals[0].id);const choices=await modelChoice.locator('option').evaluateAll(options=>options.map(option=>option.value));if(choices.some(value=>value&&!locals.some(provider=>provider.id===value)))throw Error('Learning model picker exposes a non-local provider');await panel.getByRole('checkbox',{name:'Aus neuen Gesprächen lernen',exact:true}).uncheck();await panel.getByRole('button',{name:'Gedächtniseinstellungen speichern',exact:true}).click();await panel.getByText('Gedächtniseinstellungen gespeichert.',{exact:true}).waitFor();const savedSettings=await(await page.request.get(base+'/api/memory-settings')).json();if(savedSettings.extraction_enabled||savedSettings.config.extractor_provider_id!==locals[0].id)throw Error('Learning model or setting not persisted');
 await panel.getByLabel('Memory durchsuchen',{exact:true}).fill('');await panel.getByLabel('Einträge anzeigen',{exact:true}).selectOption('');await panel.getByLabel('Art der Erinnerung',{exact:true}).selectOption('preference');
 if(process.env.MEMORY_SCREENSHOT_PATH)await page.screenshot({path:process.env.MEMORY_SCREENSHOT_PATH,fullPage:true,animations:'disabled'});const expired=await page.request.post(base+'/api/memories',{headers,data:{id:crypto.randomUUID(),title:'Synthetic expired memory',content:'Synthetic time-limited fact',storage:'app',category:'personal',fact_type:'fact',sensitivity:'private',subject:'user',predicate:'other',cloud_providers:[],valid_until:1}});if(!expired.ok())throw Error('Synthetic expired memory creation failed');await panel.getByLabel('Art der Erinnerung',{exact:true}).selectOption('');await panel.getByLabel('Einträge anzeigen',{exact:true}).selectOption('expired');const expiredRow=panel.getByRole('button').filter({hasText:'Synthetic expired memory'});await expiredRow.waitFor();if(!(await expiredRow.innerText()).includes('Abgelaufen'))throw Error('Expired memory is shown as active');await page.setViewportSize({width:320,height:700});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile memory overflow');
 if(errors.length)throw Error(errors.join('; '));console.log('Memory UI passed: app-owned local CRUD, fresh/stale sensitive review, search draft retention, CAS comparison, Escape, forget semantics, local-only learning model selection and persistence, expired status, filters and mobile. Synthetic real API only.');
}finally{await browser.close()}

}
