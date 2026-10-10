import {chromium} from 'playwright';
import {mkdir} from 'node:fs/promises';
import {loginFixture} from './fixture-login.mjs';
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:900}});
const output='../.local/composer-qa';await mkdir(output,{recursive:true});
const errors=[];page.on('pageerror',error=>errors.push(error.message));
try {
 // Isolated UI configuration exposes a cloud choice; no real provider is contacted.
 await page.route('**/api/settings',async route=>{const response=await route.fetch();const body=await response.json();await route.fulfill({response,json:{...body,cloud_enabled:true,external_provider_kinds:['openrouter']}})});
 // The isolated server intentionally denies real cloud grants; only browser choice is enabled.
 await page.route('**/api/conversations',async route=>{if(route.request().method()==='POST'){const body=route.request().postDataJSON();await route.fulfill({response:await route.fetch({postData:JSON.stringify({...body,cloud_allowed:false})})})}else await route.continue()});
 await page.goto('http://127.0.0.1:18765');await loginFixture(page);
 const composer=page.locator('form.composer'),model=composer.getByRole('button',{name:'Modellwahl',exact:true}),plus=composer.getByRole('button',{name:'Aktionen und Anhänge',exact:true});
 if(await composer.locator('select').count())throw Error('Native composer selects remain');
 await model.focus();await page.keyboard.press('ArrowDown');await page.getByRole('menu',{name:'Modellwahl',exact:true}).waitFor();
 if(!await page.getByRole('menuitemradio',{name:'Auto',exact:true}).evaluate(e=>e===document.activeElement))throw Error('Menu does not focus first option');
 await page.keyboard.press('ArrowDown');if(!await page.getByRole('menuitemradio',{name:'Nur lokal',exact:true}).evaluate(e=>e===document.activeElement))throw Error('Arrow navigation failed');
 await page.keyboard.press('Escape');if(!await model.evaluate(e=>e===document.activeElement))throw Error('Escape lost model trigger focus');
 let creates=0;page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/api/conversations'))creates++});
 await model.click();await page.getByRole('menuitemradio',{name:'Auto + OpenRouter',exact:true}).click();const cloud=page.getByRole('dialog',{name:'Cloud-Modell wählen',exact:true});await cloud.waitFor();await page.keyboard.press('Escape');if(await cloud.count()||creates)throw Error('Cloud cancellation created a grant/chat');if(!await model.evaluate(e=>e===document.activeElement))throw Error('Cloud cancel lost focus');
 await model.click();await page.getByRole('menuitemradio',{name:'Nur lokal',exact:true}).click();
 if(!await composer.getByRole('button',{name:'Websuche',exact:true}).isDisabled())throw Error('Local mode permits web search');
 await model.click();await page.getByRole('menuitemradio',{name:'Auto',exact:true}).click();
 const input=page.getByRole('textbox',{name:'Nachricht',exact:true});await input.fill('Synthetischer UX-Entwurf');const short=await input.evaluate(e=>e.getBoundingClientRect().height);
 await input.press('Shift+Enter');if(!(await input.inputValue()).includes('\n'))throw Error('Shift Enter submitted message');
 await input.fill(Array.from({length:15},(_,i)=>'Synthetische Zeile '+i).join('\n'));await page.waitForFunction(()=>document.querySelector('textarea[aria-label="Nachricht"]').getBoundingClientRect().height>=150);
 const tall=await input.evaluate(e=>e.getBoundingClientRect().height);if(tall<=short||tall>181)throw Error('Composer auto height failed');
 if(await input.evaluate(e=>getComputedStyle(e).resize)!=='none')throw Error('Native resize handle remains');
 await input.fill('Synthetischer langer Entwurf '.repeat(12));await page.setViewportSize({width:320,height:640});await page.waitForFunction(()=>document.querySelector('textarea[aria-label="Nachricht"]').getBoundingClientRect().height>=150);await page.setViewportSize({width:1440,height:900});
 await input.fill('Öffentliche synthetische Frage');
 await composer.getByRole('button',{name:'Websuche aktiviert',exact:true}).click();
 if(await page.getByRole('dialog',{name:'Websuche für diese Nachricht',exact:true}).count())throw Error('Web toggle requires a dialog');
 await input.fill('Geänderter synthetischer Entwurf');
 await composer.getByRole('button',{name:'Websuche',exact:true}).click();
 if(await composer.getByRole('button',{name:'Websuche aktiviert',exact:true}).count()!==1)throw Error('Direct web toggle failed');
 await plus.click();await page.keyboard.press('End');if(!await page.getByRole('menuitem',{name:/Antwortstil einstellen/}).evaluate(e=>e===document.activeElement))throw Error('End navigation failed');await page.keyboard.press('Home');await page.keyboard.press('Escape');
 await plus.click();await input.click();if(await page.getByRole('menu',{name:'Aktionen und Anhänge',exact:true}).count())throw Error('Outside click did not close menu');
 await plus.click();await page.getByRole('menuitem',{name:/Antwortstil einstellen/}).click();await page.getByRole('radiogroup',{name:'Antwortlänge',exact:true}).waitFor();
 await page.getByRole('button',{name:'Arbeitsbereich schließen',exact:true}).click();
 for(const [width,height] of [[320,640],[390,844],[640,360],[1440,900]]){
  await page.setViewportSize({width,height});await plus.click();const menu=page.getByRole('menu',{name:'Aktionen und Anhänge',exact:true});await menu.waitFor();
  const box=await menu.boundingBox();if(box.x<0||box.y<0||box.x+box.width>width+1||box.y+box.height>height+1)throw Error('Menu outside viewport '+width+'x'+height+': '+JSON.stringify(box));
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Composer horizontal overflow');
  await page.screenshot({path:output+'/actions-'+width+'.png'});await page.keyboard.press('Escape');
 }
 // Reload a non-chat page while restoring its linked conversation slowly.
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();await page.locator('button.new').click();
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();await page.getByRole('button',{name:'Werkzeuge',exact:true}).click();
 await page.route('**/api/conversations/*',async route=>{if(route.request().method()==='GET')await new Promise(resolve=>setTimeout(resolve,800));await route.continue()});
 await page.reload();const navigation=page.getByRole('button',{name:'Navigation öffnen',exact:true});await navigation.click();await page.getByRole('button',{name:'Werkzeuge',exact:true}).click();
 if(await page.locator('.sidebar.open').count())throw Error('Mobile navigation did not close after restored page selection');
 if(errors.length)throw Error(errors.join('\n'));console.log('Composer UX passed: actions, keyboard/focus, persistent direct web toggle, local mode, auto height and mobile/short viewport. Synthetic only.');
}finally{await browser.close();}
