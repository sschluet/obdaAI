import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
const base='http://127.0.0.1:18765';
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto(base);await loginFixture(page);
 // Delay the persisted reload to verify the footer already receives real SSE metadata.
 await page.route('**/api/conversations/*',async route=>{if(route.request().method()==='GET')await new Promise(resolve=>setTimeout(resolve,2000));await route.continue()});
 await page.getByLabel('Nachricht',{exact:true}).fill('Synthetic processing attribution check');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
 const footers=page.locator('.message.assistant .answer-processing');await footers.filter({hasText:'Lokal · synthetic-fixture'}).waitFor();
 if(!await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).isVisible())throw Error('Footer was only available after persisted reload, not SSE');
 await page.getByText('Antwort abgeschlossen',{exact:true}).waitFor();await page.getByRole('button',{name:'Nachricht senden',exact:true}).waitFor();
 await page.unroute('**/api/conversations/*');await page.reload();await footers.filter({hasText:'Lokal · synthetic-fixture'}).waitFor();
 if(await footers.count()!==1)throw Error('Footer added to user message or duplicated');if(await footers.first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize))>12)throw Error('Footer is not discreet');
 // Additional read-only synthetic API records cover providers, system replies and legacy gaps.
 await page.route('**/api/conversations/*',async route=>{if(route.request().method()!=='GET'){await route.continue();return}const response=await route.fetch();const data=await response.json();if(!Array.isArray(data.messages)){await route.fulfill({response});return}
  data.messages.push({id:'demo-cloud-answer',role:'assistant',content:'Synthetische Cloud-Antwort zur Darstellungsprüfung.',label:'LOCAL_ONLY',processing:{run_id:'demo-cloud-run',provider:'openrouter',model:'vendor/demo-model',model_used:true,status:'succeeded'}},
   {id:'demo-system-answer',role:'assistant',content:'Synthetische Systemantwort.',label:'LOCAL_ONLY',processing:{run_id:'demo-system-run',provider:'local',model:null,model_used:false,status:'succeeded'}},
   {id:'demo-cancelled-answer',role:'assistant',content:'Synthetische abgebrochene Teilantwort.',label:'LOCAL_ONLY',processing:{run_id:'demo-cancelled-run',provider:'local',model:'synthetic-fixture',model_used:true,status:'cancelled'}},
   {id:'demo-interrupted-answer',role:'assistant',content:'Synthetische unterbrochene Teilantwort.',label:'LOCAL_ONLY',processing:{run_id:'demo-interrupted-run',provider:'local',model:'synthetic-fixture',model_used:true,status:'interrupted'}},
   {id:'demo-legacy-answer',role:'assistant',content:'Synthetische ältere Antwort ohne Laufbeleg.',label:'CLOUD_ALLOWED',processing:null});await route.fulfill({response,json:data})});
 await page.reload();await footers.filter({hasText:'OpenRouter · vendor/demo-model'}).waitFor();await footers.filter({hasText:'Lokal · Systemantwort'}).waitFor();await footers.filter({hasText:'Verarbeitung nicht erfasst'}).waitFor();await footers.filter({hasText:'Teilantwort · abgebrochen'}).waitFor();await footers.filter({hasText:'Teilantwort · unterbrochen'}).waitFor();
 await page.getByRole('button',{name:'Modellwahl',exact:true}).click();await page.getByRole('menuitemradio',{name:'Nur lokal',exact:true}).click();if(await footers.filter({hasText:'OpenRouter · vendor/demo-model'}).count()!==1)throw Error('Current model choice rewrote previous answer provenance');
 await page.setViewportSize({width:390,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Processing footer mobile overflow');
 if(errors.length)throw Error(errors.join('\n'));console.log('Answer processing UI passed: real SSE and reload binding, provider/model display, no-model/unknown distinctions, cancelled/interrupted partial distinctions, selection independence and mobile. Cloud examples are read-only synthetic UI records.');
}finally{await browser.close()}
