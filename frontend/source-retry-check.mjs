// Local synthetic source only. Failure response is simulated; retry uses the real API.
import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
const base=process.env.SOURCE_RETRY_FIXTURE_URL||'http://127.0.0.1:18765';
if(!['http://127.0.0.1:18765','http://127.0.0.1:18767'].includes(base))throw Error('Synthetic fixture required');
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));let headers,project;
async function call(path,method='GET',data){const r=await page.request.fetch(base+'/api'+path,{method,headers,data});if(!r.ok())throw Error(method+' '+path+' '+r.status());return r.json()}
try{
 await page.goto(base);const auth=await loginFixture(page);headers={'X-CSRF-Token':auth.csrf,Origin:base};
 project=await call('/projects','POST',{name:'Synthetic OCR retry '+Date.now(),description:'Isolated OCR interface regression',instructions:''});
 const sources=[];for(const name of ['Scan-Beispiel.txt','Arbeitsbereich.txt']){const r=await page.request.post(base+'/api/projects/'+project.id+'/sources',{headers:{...headers,'Content-Type':'application/octet-stream','X-File-Name':name},data:Buffer.from('Synthetic OCR source '+name)});if(!r.ok())throw Error('Upload failed');sources.push(await r.json())}
 for(let i=0;i<100;i++){if((await call('/projects/'+project.id+'/sources')).every(s=>s.status==='ready'))break;if(i===99)throw Error('Sources not ready');await page.waitForTimeout(100)}
 const failed=new Set(sources.map(s=>s.id));let retries=0;
 await page.route('**/api/projects/'+project.id+'/sources',async route=>{if(route.request().method()!=='GET')return route.continue();const response=await route.fetch();const rows=await response.json();await route.fulfill({response,json:rows.map(s=>failed.has(s.id)?{...s,status:'failed',error:'OCR konnte auf einer Seite keinen lesbaren Text erkennen. Bitte Scanqualität prüfen.'}:s)})});
 for(const source of sources)await page.route('**/api/projects/'+project.id+'/sources/'+source.id+'/retry',async route=>{retries++;failed.delete(source.id);await route.continue()});
 await page.reload();await page.getByRole('button',{name:'Projekte',exact:true}).click();await page.getByRole('button',{name:project.name,exact:true}).click();await page.getByRole('tab',{name:/Quellen ·/}).click();
 const first=page.locator('.source-list li').filter({hasText:'Scan-Beispiel.txt'});await first.getByRole('alert').filter({hasText:'Scanqualität'}).waitFor();if(retries!==0)throw Error('Automatic retry occurred');
 await page.setViewportSize({width:390,height:844});const retry=first.getByRole('button',{name:'Quelle erneut verarbeiten: Scan-Beispiel.txt',exact:true});await retry.focus();await page.keyboard.press('Enter');await first.getByText('Bereit',{exact:true}).waitFor();
 if(retries!==1)throw Error('Project retry duplicated');const current=await call('/projects/'+project.id+'/sources');if(current.find(s=>s.id===sources[0].id).revision!==2)throw Error('Real retry revision absent');
 await first.getByText('Quelle und Original',{exact:true}).click();const original=await page.request.get(base+'/api/projects/'+project.id+'/sources/'+sources[0].id+'/original');if((await original.body()).toString()!=='Synthetic OCR source Scan-Beispiel.txt')throw Error('Original changed');
 await page.setViewportSize({width:1440,height:1000});await page.getByRole('tab',{name:/Gespräche ·/}).click();await page.getByRole('button',{name:'Neues Projektgespräch',exact:true}).click();await page.getByRole('button',{name:'Aktionen und Anhänge',exact:true}).click();await page.getByRole('menuitem',{name:/Quellen/}).click();
 const bench=page.getByRole('complementary',{name:'Arbeitsbereich neben dem Chat',exact:true});await bench.getByRole('alert').filter({hasText:'Scanqualität'}).waitFor();await bench.getByRole('link',{name:'Original herunterladen',exact:true}).waitFor();await bench.getByRole('button',{name:'Quelle erneut verarbeiten: Arbeitsbereich.txt',exact:true}).click();await bench.getByText('Verarbeitet · Version 2',{exact:true}).waitFor();if(retries!==2)throw Error('Workspace retry duplicated');
 if(errors.length)throw Error(errors.join('; '));console.log('Source retry UX passed: explicit local retry in project and workspace, visible safe error, mobile keyboard activation, real API revision, no automatic retry and unchanged original. Failed status is synthetic.');
}finally{
 if(project&&headers){const r=await page.request.get(base+'/api/projects/'+project.id+'/deletion');if(r.ok()){const preview=await r.json();if(!preview.blockers.length)await page.request.delete(base+'/api/projects/'+project.id,{headers,data:{expected_state:preview.expected_state}})}}await browser.close();
}
