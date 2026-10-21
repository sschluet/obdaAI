// Capture only the real Memory UI against a fresh, synthetic loopback fixture.
import {chromium} from 'playwright';
import {fileURLToPath} from 'node:url';
import {loginFixture} from './fixture-login.mjs';
const base=process.env.MEMORY_FIXTURE_URL||'http://127.0.0.1:18769';
if(base!=='http://127.0.0.1:18769')throw Error('Only the dedicated synthetic memory fixture is permitted');
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:1600},deviceScaleFactor:1});
const errors=[];page.on('pageerror',error=>errors.push(error.message));
try{
 await page.goto(base);const auth=await loginFixture(page),headers={Origin:base,'X-CSRF-Token':auth.csrf};
 const response=await page.request.post(base+'/api/memories',{headers,data:{id:crypto.randomUUID(),title:'Beispiel: bevorzugte Sprache',content:'Für das fiktive Projekt Aurora bevorzuge ich kurze Antworten auf Deutsch. Ausschließlich synthetische Beispieldaten.',storage:'app',category:'preference',fact_type:'fact',subject:'user',predicate:'language',sensitivity:'private',cloud_providers:[]}});
 if(!response.ok())throw Error('Synthetic memory seed failed');
 await page.getByRole('button',{name:'Wissen',exact:true}).click();await page.getByRole('tab',{name:'Persönliche Merkliste',exact:true}).click();
 const panel=page.getByRole('region',{name:'Gedächtnis',exact:true});await panel.getByLabel('Speicherort',{exact:true}).waitFor();
 await panel.getByRole('button').filter({hasText:'Beispiel: bevorzugte Sprache'}).click();await panel.getByText('So lernt dein Gedächtnis',{exact:true}).click();
 await panel.getByLabel('Modell zum Lernen',{exact:true}).waitFor();
 await page.screenshot({path:fileURLToPath(new URL('../website/assets/memory.png',import.meta.url)),fullPage:true,animations:'disabled'});
 if(errors.length)throw Error(errors.join('; '));console.log('Synthetic Memory UI screenshot captured; no real history, account data or model acceptance.');
}finally{await browser.close()}
