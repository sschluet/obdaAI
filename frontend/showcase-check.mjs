// Check the public website independently of the private application.
import {chromium} from 'playwright';
import {mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const base=process.env.SHOWCASE_URL||'http://127.0.0.1:18768';
const output=fileURLToPath(new URL('../.local/showcase-qa/',import.meta.url));await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1080}});
const errors=[];const failed=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('response',r=>{if(r.status()>=400)failed.push(r.url());});
try{
 await page.goto(base);
 await page.locator('.feature-card').first().waitFor();
 if(await page.locator('.feature-card').count()!==43)throw Error('Feature catalog incomplete');
 await page.getByRole('button',{name:'Chat & Modelle',exact:true}).click();
 if(await page.locator('.feature-card').count()!==6)throw Error('Category filter failed');
 await page.getByRole('button',{name:'Alle Features',exact:true}).click();
 await page.getByLabel('Features durchsuchen').fill('PDF-Aufteilung');
 if(await page.locator('.feature-card').count()!==1)throw Error('Feature search failed');
 await page.getByLabel('Features durchsuchen').fill('no-such-feature');
 await page.getByText('Keine passende Funktion gefunden.',{exact:false}).waitFor();
 await page.getByLabel('Features durchsuchen').fill('');
 for(const name of ['Chat','Projekte','Dateien','Aufgaben','Wissen']){
  await page.getByRole('tab',{name,exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#gallery-image').complete&&document.querySelector('#gallery-image').naturalWidth>0);
 }
 await page.getByRole('button',{name:'Screenshot vergrößern',exact:false}).click();
 await page.getByRole('dialog').waitFor();
 await page.keyboard.press('Escape');
 await page.getByRole('tab',{name:'Chat',exact:true}).click();
 await page.keyboard.press('ArrowRight');
 if(await page.getByRole('tab',{name:'Projekte',exact:true}).getAttribute('aria-selected')!=='true')throw Error('Keyboard gallery failed');
 await page.getByRole('tab',{name:'Chat',exact:true}).click();
 await page.evaluate(()=>scrollTo(0,0));
 await page.screenshot({path:output+'/desktop.png',fullPage:true});
 await page.screenshot({path:output+'/desktop-first-fold.png'});
 await page.setViewportSize({width:390,height:844});
 await page.evaluate(()=>scrollTo(0,0));
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile horizontal overflow');
 await page.screenshot({path:output+'/mobile.png',fullPage:true});
 await page.screenshot({path:output+'/mobile-first-fold.png'});
 for(const width of [320,768,1024]){
  await page.setViewportSize({width,height:900});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Overflow at '+width);
 }
 if(errors.length||failed.length)throw Error(JSON.stringify({errors,failed}));
 console.log('Showcase passed: 43 features, search/categories, all gallery assets, dialog/Escape/keyboard and 320–1440px layouts.');
}finally{await browser.close();}
