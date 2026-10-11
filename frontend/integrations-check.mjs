import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const base='http://127.0.0.1:18765';let headers,ownedProject,originalPolicy;
async function call(path,method='GET',data){const response=await page.request.fetch(base+'/api'+path,{method,headers,data});if(!response.ok())throw Error(method+' '+path+': '+await response.text());return response.status()===204?null:response.json()}
const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('http://127.0.0.1:18765');const auth=await loginFixture(page);headers={'X-CSRF-Token':auth.csrf,Origin:base};originalPolicy=await call('/action-policy');ownedProject=await call('/projects','POST',{name:'Synthetic integration archive '+Date.now(),description:'Owned integration workflow fixture',instructions:''});
 if(await page.locator('aside nav').getByRole('button',{name:'Werkzeuge',exact:true}).count())throw Error('Tools still in primary navigation');
 await page.getByRole('button',{name:'Einstellungen',exact:true}).click();
 await page.getByRole('button',{name:'Integrationen',exact:true}).click();
 await page.getByText('Bestehende Systemaktionen',{exact:true}).click();
 await page.getByRole('heading',{name:'Arbeitsraum im Überblick',exact:true}).waitFor();
 const hub=page.locator('.integration-card').filter({has:page.getByRole('heading',{name:'Arbeitsraum im Überblick',exact:true})});
 let executes=0,fail=true;
 await page.route('**/api/actions/*/execute',async route=>{executes++;if(fail){fail=false;await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Synthetischer Verbindungsfehler'})});return}await route.continue()});
 await hub.getByRole('button',{name:'Überblick anzeigen',exact:true}).click();
 await hub.getByRole('alert').waitFor();
 await hub.getByRole('button',{name:'Erneut versuchen',exact:true}).click();
 await hub.locator('.integration-result').getByText(/Projekte? ·/).waitFor();
 if(executes!==2)throw Error('Read retry failed or duplicate action execution');
 await page.unroute('**/api/actions/*/execute');
 const archive=page.locator('.integration-card').filter({has:page.getByRole('heading',{name:'Projekt archivieren',exact:true})});
 await archive.getByRole('button',{name:'Projekt auswählen',exact:true}).click();
 if(await archive.locator('select').count())throw Error('Archive picker still native select');
 await archive.getByLabel('Projekte suchen',{exact:true}).fill('No matching synthetic project xyz');
 await archive.getByText('Keine passenden aktiven Projekte.',{exact:true}).waitFor();
 if(await archive.getByRole('button',{name:'Archivierung prüfen',exact:true}).isEnabled())throw Error('Empty selection permits preparation');

 if(originalPolicy.paused)await archive.getByRole('button',{name:'Einzelne Änderungen erlauben',exact:true}).click();
 await page.getByRole('button',{name:'Datenschutz',exact:true}).click();
 await page.getByRole('heading',{name:'Datenverarbeitung und Aktionen',exact:true}).waitFor();
 await page.locator('.setting-card b').getByText('Einzeln freigeben',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Integrationen',exact:true}).click();
 await page.getByText('Bestehende Systemaktionen',{exact:true}).click();
 await archive.getByRole('button',{name:'Projekt auswählen',exact:true}).click();
 await archive.getByLabel('Projekte suchen',{exact:true}).fill(ownedProject.name);
 await archive.getByRole('button',{name:ownedProject.name,exact:true}).click();
 async function prepare(){await archive.getByRole('button',{name:'Archivierung prüfen',exact:true}).click();await archive.getByRole('button',{name:'Diese Archivierung freigeben',exact:true}).waitFor()}
 async function grant(){await archive.getByRole('button',{name:'Diese Archivierung freigeben',exact:true}).click();await archive.getByRole('button',{name:'Projekt jetzt archivieren',exact:true}).waitFor()}
 await prepare();await grant();
 const beforeCollapse=(await call('/actions')).find(a=>a.tool_id==='project.archive'&&a.parameters.project_id===ownedProject.id);
 await archive.getByRole('button',{name:'Auswahl schließen',exact:true}).click();
 await archive.getByRole('button',{name:'Projekt auswählen',exact:true}).click();
 await archive.getByRole('button',{name:'Projekt jetzt archivieren',exact:true}).waitFor();
 const afterReopen=(await call('/actions')).find(a=>a.tool_id==='project.archive'&&a.parameters.project_id===ownedProject.id);
 if(afterReopen.id!==beforeCollapse.id||afterReopen.status!=='approved')throw Error('Collapsing lost approved archive review');
 if((await call('/projects/'+ownedProject.id)).archived)throw Error('Grant executed without final review click');
 await archive.getByRole('button',{name:'Abbrechen',exact:true}).click();
 if((await call('/projects/'+ownedProject.id)).archived)throw Error('Cancel modified target project');
 await archive.getByRole('button',{name:ownedProject.name,exact:true}).click();await prepare();await grant();
 const current=await call('/projects/'+ownedProject.id);await call('/projects/'+ownedProject.id,'PATCH',{name:current.name,description:'Changed after approval',instructions:'',revision:current.revision,archived:false});
 await archive.getByRole('button',{name:'Projekt jetzt archivieren',exact:true}).click();await archive.getByRole('alert').waitFor();
 if((await call('/projects/'+ownedProject.id)).archived)throw Error('Stale revision archived project');
 await archive.getByRole('button',{name:'Abbrechen',exact:true}).click();
 await archive.getByRole('button',{name:ownedProject.name,exact:true}).click();await prepare();await grant();
 await archive.getByRole('button',{name:'Projekt jetzt archivieren',exact:true}).click();await archive.getByText(/Projekt archiviert · neue Revision/).waitFor();
 if(!(await call('/projects/'+ownedProject.id)).archived)throw Error('Reviewed archive did not execute');
 for(const title of ['Modelle, Recherche und Zeitplanung','Bisherige MCP-Verbindungen'])if(await page.getByText(title,{exact:true}).count())throw Error('Duplicate integrations section: '+title);
 if(await page.getByRole('button',{name:'Weitere Verbindungen und Einrichtung',exact:true}).count())throw Error('Obsolete connections CTA still present');
 await page.setViewportSize({width:390,height:844});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile integration overflow');
 await page.setViewportSize({width:1440,height:1000});
 await page.route('**/api/tools',async route=>{const response=await route.fetch();const tools=await response.json();await route.fulfill({response,json:tools.map(t=>t.id==='ha.inspect'?{...t,configured:false}:t)})});
 await page.reload();await page.getByText('Bestehende Systemaktionen',{exact:true}).click();await page.getByRole('heading',{name:'Status und Updates',exact:true}).waitFor();
 const ha=page.locator('.integration-card').filter({has:page.getByRole('heading',{name:'Status und Updates',exact:true})});
 if(await ha.getByRole('button',{name:'Status prüfen',exact:true}).isEnabled())throw Error('Unconfigured integration is runnable');
 await ha.getByText('Nicht eingerichtet',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Änderungen pausieren',exact:true}).click();
 await page.getByRole('button',{name:'Datenschutz',exact:true}).click();
 await page.getByRole('heading',{name:'Datenverarbeitung und Aktionen',exact:true}).waitFor();
 await page.locator('.setting-card b').getByText('Pausiert',{exact:true}).waitFor();
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Integrations UX passed: navigation, adjacent read result, retry, project search, configuration status, deduplicated settings and mobile.');
}finally{
 if(headers&&originalPolicy){const policy=await call('/action-policy');if(policy.paused!==originalPolicy.paused)await call('/action-policy','PATCH',{paused:originalPolicy.paused,expected_revision:policy.revision})}
 if(headers&&ownedProject){const preview=await call('/projects/'+ownedProject.id+'/deletion');if(!preview.blockers.length)await call('/projects/'+ownedProject.id,'DELETE',{expected_state:preview.expected_state})}
 await browser.close()
}
