import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
page.on('pageerror',error=>errors.push(error.message));
const response=(query,results=[],has_more=false)=>({query,results,has_more,limit:30});
const demo=(kind,id,title)=>({kind,id,title,subtitle:'Synthetische lokale Suchprüfung',project_id:null,matched_in:'title'});
const requests=[];
try{
 await page.goto('http://127.0.0.1:18765');await loginFixture(page);
 await page.getByLabel('Nachricht',{exact:true}).fill('Ungesendeter Suchprüfungsentwurf');
 await page.route('**/api/workspace/search?*',async route=>{
  const url=new URL(route.request().url()),query=url.searchParams.get('q'),kind=url.searchParams.get('kind');requests.push({query,kind});
  if(query==='langsam')await new Promise(resolve=>setTimeout(resolve,650));
  if(query==='fehler'){await route.fulfill({status:503,json:{detail:'Synthetische Suche vorübergehend nicht verfügbar'}});return}
  const rows=query==='leer'?[]:query==='langsam'?[demo('conversation','old','Veralteter Treffer')]:query==='neu'?[demo('project','new','Aktueller Treffer')]:Array.from({length:16},(_,index)=>demo(['conversation','project','artifact','source','task','knowledge'][index%6],String(index),'Lokaler Treffer '+index));
  await route.fulfill({json:response(query,rows,query==='viele')});
 });
 await page.keyboard.press('Control+k');
 const dialog=page.getByRole('dialog',{name:'Suchen und weiterarbeiten',exact:true}),input=dialog.getByRole('combobox',{name:'Arbeitsraum durchsuchen',exact:true});await dialog.waitFor();
 if(!await input.evaluate(element=>element===document.activeElement))throw Error('Search did not autofocus input');
 await input.fill('a');await page.waitForTimeout(250);if(requests.length)throw Error('Search transmitted too-short text');
 await input.fill('viele');await dialog.getByRole('option').first().waitFor();
 if(await dialog.getByRole('option').count()!==16)throw Error('Search result missing');
 await input.press('End');if(await input.getAttribute('aria-activedescendant')!==await dialog.getByRole('option').last().getAttribute('id'))throw Error('End did not select last result');
 await input.press('ArrowDown');if(await input.getAttribute('aria-activedescendant')!==await dialog.getByRole('option').first().getAttribute('id'))throw Error('ArrowDown did not wrap');
 await input.press('ArrowUp');await input.press('Home');
 if(await input.getAttribute('aria-activedescendant')!==await dialog.getByRole('option').first().getAttribute('id'))throw Error('Home did not select first result');
 await dialog.getByRole('button',{name:'Dateien',exact:true}).click();await page.waitForResponse(r=>r.url().includes('/workspace/search?')&&r.url().includes('kind=artifact'));
 if(requests.at(-1)?.kind!=='artifact')throw Error('Filter did not reach server');
 await input.fill('langsam');await page.waitForRequest(r=>r.url().includes('q=langsam'));await input.fill('neu');
 if(await dialog.getByRole('option').count())throw Error('Previous results visible for new query');
 await dialog.getByRole('option').filter({hasText:'Aktueller Treffer'}).waitFor();await page.waitForTimeout(750);
 if(await dialog.getByText('Veralteter Treffer',{exact:true}).count())throw Error('Stale response replaced latest results');
 await input.fill('leer');await dialog.getByText('Keine passenden Treffer',{exact:true}).waitFor();
 await input.fill('fehler');await dialog.getByRole('button',{name:'Erneut versuchen',exact:true}).waitFor();
 const before=requests.length;await dialog.getByRole('button',{name:'Erneut versuchen',exact:true}).click();await page.waitForTimeout(350);if(requests.length<=before)throw Error('Retry did not submit request');
 await input.fill('viele');await dialog.getByRole('option').first().waitFor();
 await dialog.getByRole('button',{name:'Suche schließen',exact:true}).focus();await page.keyboard.press('Shift+Tab');
 if(!await dialog.getByRole('button',{name:'Wissen',exact:true}).evaluate(element=>element===document.activeElement))throw Error('Search focus trap did not wrap');
 await page.keyboard.press('Tab');if(!await dialog.getByRole('button',{name:'Suche schließen',exact:true}).evaluate(element=>element===document.activeElement))throw Error('Search focus trap left dialog');
 await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
 if(await page.getByLabel('Nachricht',{exact:true}).inputValue()!=='Ungesendeter Suchprüfungsentwurf')throw Error('Search lost chat draft');
 const trigger=page.getByRole('button',{name:'Arbeitsraum durchsuchen',exact:true});await trigger.click();await dialog.waitFor();
 await input.fill('viele');await dialog.getByRole('option').first().waitFor();
 for(const size of [{width:320,height:568},{width:390,height:320}]){
  await page.setViewportSize(size);await input.press('End');
  if(await dialog.evaluate(element=>element.scrollWidth>element.clientWidth))throw Error('Mobile search has horizontal overflow');
  const bounds=await dialog.boundingBox();if(bounds.y<0||bounds.y+bounds.height>size.height+1)throw Error('Search exceeds mobile viewport');
  const closeBounds=await dialog.getByRole('button',{name:'Suche schließen',exact:true}).boundingBox();if(closeBounds.y<0||closeBounds.y+closeBounds.height>size.height)throw Error('Mobile close button inaccessible');
 }
 await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
 if(!await trigger.evaluate(element=>element===document.activeElement))throw Error('Search did not restore trigger focus');
 await trigger.click();await dialog.waitFor();if(await input.inputValue())throw Error('Search retained query after closing');
 await page.setViewportSize({width:1440,height:900});await page.locator('.search-palette-overlay').click({position:{x:5,y:5}});await dialog.waitFor({state:'hidden'});
 if(await page.evaluate(()=>Object.keys(sessionStorage).some(key=>/search/i.test(key)))||await page.evaluate(()=>location.search.includes('viele')))throw Error('Search text persisted outside dialog');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Search palette passed: debounced local GET, minimum input, filters, stale suppression, empty/error/retry, keyboard navigation/focus trap, draft preservation, mobile short viewport and ephemeral query. Result navigation is validated separately against real synthetic objects.');
}finally{await browser.close()}
