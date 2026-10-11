import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
const base='http://127.0.0.1:18765';
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});let headers,project;const ownedCases=[];const choiceName='Synthetic choice '+Date.now();
const errors=[];page.on('pageerror',e=>errors.push(e.message));
async function chooseProject(scope,label,name){await scope.getByRole('button',{name:label,exact:true}).click();const picker=scope.getByRole('dialog',{name:label+' auswählen',exact:true});await picker.getByRole('button',{name,exact:true}).click()}
async function call(path,method='GET',data){const response=await page.request.fetch(base+'/api'+path,{method,headers,data});if(!response.ok())throw Error(method+' '+path+': '+await response.text());return response.json()}
try{
 await page.goto(base);const auth=await loginFixture(page);headers={'X-CSRF-Token':auth.csrf,Origin:base};const noProjects=route=>route.fulfill({json:[]});await page.route('**/api/projects',noProjects);
 await page.getByRole('navigation',{name:'Hauptnavigation'}).getByRole('button',{name:'Use Cases',exact:true}).click();
 const names=await page.getByRole('navigation',{name:'Hauptnavigation'}).getByRole('button').allTextContents();if(names.indexOf('Use Cases')!==names.indexOf('Projekte')+1||names.indexOf('Aufgaben')!==names.indexOf('Use Cases')+1)throw Error('Use Cases navigation order');
 await page.locator('.use-cases-hub').getByRole('button',{name:'Neuer Use Case',exact:true}).click();
 const panel=page.locator('.use-cases-panel');
 const builder=panel.locator('.uc-builder');const trigger=builder.getByRole('button',{name:'Projektbezug',exact:true});await trigger.click();await builder.getByRole('dialog',{name:'Projektbezug auswählen',exact:true}).getByRole('searchbox',{name:'Projekte suchen',exact:true}).waitFor();await page.keyboard.press('Escape');if(await builder.getByRole('dialog',{name:'Projektbezug auswählen',exact:true}).count()||!await trigger.evaluate(el=>el===document.activeElement))throw Error('Picker Escape/focus failed');await builder.getByLabel('Name',{exact:true}).fill('Synthetic monthly report');
 await builder.getByLabel('Feldname',{exact:true}).fill('Objekt');await builder.getByRole('button',{name:'Feld hinzufügen',exact:true}).click();
 await builder.getByLabel('Feldname',{exact:true}).nth(1).fill('Betrag');await builder.locator('.uc-field-editor').nth(1).getByRole('button',{name:'Zahl',exact:true}).click();
 await builder.getByRole('button',{name:'Diagramm',exact:true}).click();
 await builder.getByRole('button',{name:'Spalte nach oben: Betrag',exact:true}).click();
 await builder.getByRole('button',{name:'Use Case speichern',exact:true}).click();
 await panel.getByLabel('Objekt *',{exact:true}).fill('=SUM(1)');await panel.getByLabel('Betrag *',{exact:true}).fill('-42.5');
 await panel.getByRole('button',{name:'Ergebnis erstellen und Eingabe speichern',exact:true}).click();
 await panel.getByRole('region',{name:'Ergebnis',exact:true}).getByRole('cell',{name:'-42.5',exact:true}).waitFor();
 await panel.locator('.uc-chart').waitFor();if(!await panel.locator('.uc-bar.negative').count())throw Error('Negative BI values not distinguished');
 await page.unroute('**/api/projects',noProjects);
 const cases=await call('/use-cases');const item=cases.find(row=>row.spec.name==='Synthetic monthly report');ownedCases.push(item.id);if(item.project_id!==null)throw Error('Standalone creation unexpectedly bound a project');const prefix='/use-cases/'+item.id;
 const csv=await page.request.get(base+'/api'+prefix+'/output.csv');if(!csv.ok()||!(await csv.text()).includes("-42.5;'=SUM(1)"))throw Error('Column order, numeric CSV or formula escaping failed');
 const xlsx=await page.request.get(base+'/api'+prefix+'/output.xlsx');const bytes=await xlsx.body();if(!xlsx.ok()||bytes.subarray(0,2).toString()!=='PK'||!xlsx.headers()['content-type'].includes('spreadsheetml'))throw Error('No actual XLSX workbook');
 await panel.getByRole('button',{name:'Bearbeiten',exact:true}).click();await builder.getByRole('button',{name:'Frage für Frage',exact:true}).click();await builder.getByRole('button',{name:'Textvorlage',exact:true}).click();
 const current=item.spec;await builder.getByLabel(/^Textvorlage/).fill('Objekt {feld_1}: {'+current.fields[1].key+'}');await builder.getByRole('button',{name:'Use Case speichern',exact:true}).click();
 await panel.getByLabel('Objekt *',{exact:true}).fill('Wizard');await panel.getByRole('button',{name:'Weiter',exact:true}).click();if((await call(prefix+'/runs')).length!==1)throw Error('Wizard navigation executed without final submit');await panel.getByLabel('Betrag *',{exact:true}).fill('0');await panel.getByRole('button',{name:'Ergebnis erstellen',exact:true}).click();
 await panel.locator('.uc-template-result').getByText('Objekt Wizard: 0',{exact:true}).waitFor();
 const runs=await call(prefix+'/runs');if(runs.length!==2||runs[0].revision!==2||runs[1].revision!==1)throw Error('Immutable history or revision change lost: '+JSON.stringify(runs.map(r=>({revision:r.revision,created:r.created}))));
 if(!(await (await page.request.get(base+'/api'+prefix+'/output.csv')).text()).includes('0;Wizard'))throw Error('Current revision output missing');
 await page.reload();await panel.locator('.uc-history-row').first().waitFor();
 if(new URL(page.url()).searchParams.get('view')!=='Use Cases'||new URL(page.url()).searchParams.get('useCase')!==item.id)throw Error('Use Cases route lost on reload');
 for(const width of [320,390,768]){await page.setViewportSize({width,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Use Cases overflow at '+width)}
 await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('button',{name:'Zur Übersicht',exact:true}).click();await chooseProject(page.locator('.use-cases-hub'),'Nach Projekt filtern','Ohne Projekt');await page.getByLabel('Use Cases suchen',{exact:false}).fill('Synthetic monthly');await page.locator('.use-cases-hub .uc-card').filter({hasText:'Synthetic monthly report'}).click();await panel.locator('.uc-history-row').first().waitFor();
 project=await call('/projects','POST',{name:'Synthetic Use Cases '+Date.now()});
 await page.goto(base+'/?view=Use+Cases&project='+project.id+'&useCase='+item.id);await panel.locator('.uc-history-row').first().waitFor();
 await panel.getByRole('button',{name:'Bearbeiten',exact:true}).click();if(!await builder.getByRole('button',{name:'Projektbezug',exact:true}).getByText('Ohne Projekt',{exact:true}).count())throw Error('Stale URL silently rebound standalone draft');await chooseProject(builder,'Projektbezug',project.name);await builder.getByRole('button',{name:'Use Case speichern',exact:true}).click();await panel.locator('.uc-history-row').first().waitFor();
 const linked=(await call('/use-cases')).find(row=>row.id===item.id);if(linked.project_id!==project.id||linked.revision!==3||(await call(prefix+'/runs')).length!==2)throw Error('Project binding lost revisions or history');

 await page.goto(base+'/?view=Projekte&project='+project.id+'&projectTab=use-cases');await panel.getByRole('button',{name:'Synthetic monthly report'}).click();if(new URL(page.url()).searchParams.get('view')!=='Use Cases')throw Error('Legacy project link not redirected');
 await panel.getByRole('button',{name:'Bearbeiten',exact:true}).click();await chooseProject(builder,'Projektbezug','Ohne Projekt');await builder.getByRole('button',{name:'Use Case speichern',exact:true}).click();await panel.locator('.uc-history-row').first().waitFor();
 const detached=(await call('/use-cases')).find(row=>row.id===item.id);if(detached.project_id!==null||detached.revision!==4||(await call(prefix+'/runs')).length!==2)throw Error('Detaching project lost revisions or history');
 const preview=await call('/projects/'+project.id+'/deletion');await call('/projects/'+project.id,'DELETE',{expected_state:preview.expected_state});project=null;
 if((await call(prefix+'/runs')).length!==2)throw Error('Project deletion removed detached history');
 await panel.getByRole('button',{name:'Löschen',exact:true}).click();await panel.getByRole('button',{name:'Abbrechen',exact:true}).click();if(!(await call('/use-cases')).some(row=>row.id===item.id))throw Error('Cancel removed definition');
 await panel.getByRole('button',{name:'Löschen',exact:true}).click();await panel.getByRole('button',{name:'Endgültig löschen',exact:true}).click();await page.locator('.use-cases-hub').getByRole('button',{name:'Neuer Use Case',exact:true}).waitFor();
 if((await call('/use-cases')).some(row=>row.id===item.id))throw Error('Use Case delete failed');await page.locator('.use-cases-hub').getByRole('button',{name:'Neuer Use Case',exact:true}).click();await builder.getByLabel('Name',{exact:true}).fill(choiceName);await builder.getByLabel('Feldname',{exact:true}).fill('Priorität');await builder.getByRole('button',{name:'Auswahl',exact:true}).click();await builder.getByLabel(/^Optionen \(eine pro Zeile\)/).fill('Normal\nDringend');await builder.getByRole('button',{name:'Use Case speichern',exact:true}).click();
 await panel.getByRole('radio',{name:'Normal',exact:true}).waitFor();
 const choice=(await call('/use-cases')).find(row=>row.spec.name===choiceName);ownedCases.push(choice.id);await panel.getByRole('button',{name:'Ergebnis erstellen und Eingabe speichern',exact:true}).click();if((await call('/use-cases/'+choice.id+'/runs')).length)throw Error('Required choice accepted no selection');const normal=panel.getByRole('radio',{name:'Normal',exact:true});await normal.focus();await page.keyboard.press('ArrowRight');if(!await panel.getByRole('radio',{name:'Dringend',exact:true}).isChecked())throw Error('Choice radio keyboard failed');await panel.getByRole('button',{name:'Ergebnis erstellen und Eingabe speichern',exact:true}).click();await panel.getByRole('region',{name:'Ergebnis',exact:true}).getByRole('cell',{name:'Dringend',exact:true}).waitFor();
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Use Cases UX passed: standalone navigation order, project-optional creation with zero visible projects, accessible choice chips, bind/detach without losing results, independent history survives project deletion, searchable project picker, direct field types, global overview/search, canonical links/reload, legacy redirect, builder, typed form, BI, ordered safe CSV, actual XLSX, wizard, zero text value, immutable revisions, reload, 320/390/768, delete/cancel');
}finally{for(const id of ownedCases){try{const row=(await call('/use-cases')).find(item=>item.id===id);if(row)await call('/use-cases/'+id,'DELETE',{expected_revision:row.revision})}catch(e){console.error('Owned standalone fixture cleanup failed: '+e.message)}}if(project){try{const preview=await call('/projects/'+project.id+'/deletion');await call('/projects/'+project.id,'DELETE',{expected_state:preview.expected_state})}catch(e){console.error('Owned Use Cases fixture cleanup failed: '+e.message)}}await browser.close()}
