import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
const base='http://127.0.0.1:18765';
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});let headers,project;
const errors=[];page.on('pageerror',e=>errors.push(e.message));
async function call(path,method='GET',data){const response=await page.request.fetch(base+'/api'+path,{method,headers,data});if(!response.ok())throw Error(method+' '+path+': '+await response.text());return response.json()}
try{
 await page.goto(base);const auth=await loginFixture(page);headers={'X-CSRF-Token':auth.csrf,Origin:base};project=await call('/projects','POST',{name:'Synthetic Use Cases '+Date.now()});
 await page.getByRole('navigation',{name:'Hauptnavigation'}).getByRole('button',{name:'Use Cases',exact:true}).click();
 const names=await page.getByRole('navigation',{name:'Hauptnavigation'}).getByRole('button').allTextContents();if(names.indexOf('Use Cases')!==names.indexOf('Projekte')+1||names.indexOf('Aufgaben')!==names.indexOf('Use Cases')+1)throw Error('Use Cases navigation order');
 await page.locator('.use-cases-hub').getByRole('button',{name:'Neuer Use Case',exact:true}).click();await page.locator('.use-cases-hub').getByLabel('Projektkontext',{exact:true}).selectOption(project.id);await page.getByRole('button',{name:'Weiter zum Entwurf',exact:true}).click();
 const panel=page.locator('.use-cases-panel');
 const builder=panel.locator('.uc-builder');await builder.getByLabel('Name',{exact:true}).fill('Synthetic monthly report');
 await builder.getByLabel('Feldname',{exact:true}).fill('Objekt');await builder.getByRole('button',{name:'Feld hinzufügen',exact:true}).click();
 await builder.getByLabel('Feldname',{exact:true}).nth(1).fill('Betrag');await builder.getByRole('combobox').nth(1).selectOption('number');
 await builder.getByRole('button',{name:'Diagramm',exact:true}).click();
 await builder.getByRole('button',{name:'Spalte nach oben: Betrag',exact:true}).click();
 await builder.getByRole('button',{name:'Use Case speichern',exact:true}).click();
 await panel.getByLabel('Objekt *',{exact:true}).fill('=SUM(1)');await panel.getByLabel('Betrag *',{exact:true}).fill('-42.5');
 await panel.getByRole('button',{name:'Ergebnis erstellen und Eingabe speichern',exact:true}).click();
 await panel.getByRole('region',{name:'Ergebnis',exact:true}).getByRole('cell',{name:'-42.5',exact:true}).waitFor();
 await panel.locator('.uc-chart').waitFor();if(!await panel.locator('.uc-bar.negative').count())throw Error('Negative BI values not distinguished');
 const cases=await call('/projects/'+project.id+'/use-cases');const item=cases[0];const prefix='/projects/'+project.id+'/use-cases/'+item.id;
 const csv=await page.request.get(base+'/api'+prefix+'/output.csv');if(!csv.ok()||!(await csv.text()).includes("-42.5;'=SUM(1)"))throw Error('Column order, numeric CSV or formula escaping failed');
 const xlsx=await page.request.get(base+'/api'+prefix+'/output.xlsx');const bytes=await xlsx.body();if(!xlsx.ok()||bytes.subarray(0,2).toString()!=='PK'||!xlsx.headers()['content-type'].includes('spreadsheetml'))throw Error('No actual XLSX workbook');
 await panel.getByRole('button',{name:'Bearbeiten',exact:true}).click();await builder.getByRole('button',{name:'Frage für Frage',exact:true}).click();await builder.getByRole('button',{name:'Textvorlage',exact:true}).click();
 const current=cases[0].spec;await builder.getByLabel(/^Textvorlage/).fill('Objekt {feld_1}: {'+current.fields[1].key+'}');await builder.getByRole('button',{name:'Use Case speichern',exact:true}).click();
 await panel.getByLabel('Objekt *',{exact:true}).fill('Wizard');await panel.getByRole('button',{name:'Weiter',exact:true}).click();if((await call(prefix+'/runs')).length!==1)throw Error('Wizard navigation executed without final submit');await panel.getByLabel('Betrag *',{exact:true}).fill('0');await panel.getByRole('button',{name:'Ergebnis erstellen',exact:true}).click();
 await panel.locator('.uc-template-result').getByText('Objekt Wizard: 0',{exact:true}).waitFor();
 const runs=await call(prefix+'/runs');if(runs.length!==2||runs[0].revision!==2||runs[1].revision!==1)throw Error('Immutable history or revision change lost: '+JSON.stringify(runs.map(r=>({revision:r.revision,created:r.created}))));
 if(!(await (await page.request.get(base+'/api'+prefix+'/output.csv')).text()).includes('0;Wizard'))throw Error('Current revision output missing');
 await page.reload();await panel.locator('.uc-history-row').first().waitFor();
 if(new URL(page.url()).searchParams.get('view')!=='Use Cases'||new URL(page.url()).searchParams.get('useCase')!==item.id)throw Error('Use Cases route lost on reload');
 for(const width of [320,390,768]){await page.setViewportSize({width,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Use Cases overflow at '+width)}
 await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('button',{name:'Zur Übersicht',exact:true}).click();await page.getByRole('combobox',{name:'Nach Projekt filtern',exact:true}).selectOption(project.id);await page.getByLabel('Use Cases suchen',{exact:false}).fill('Synthetic monthly');await page.locator('.use-cases-hub .uc-card').filter({hasText:'Synthetic monthly report'}).click();await panel.locator('.uc-history-row').first().waitFor();
 await page.goto(base+'/?view=Projekte&project='+project.id+'&projectTab=use-cases');await panel.getByRole('button',{name:'Synthetic monthly report'}).click();if(new URL(page.url()).searchParams.get('view')!=='Use Cases')throw Error('Legacy project link not redirected');
 await panel.getByRole('button',{name:'Löschen',exact:true}).click();await panel.getByRole('button',{name:'Abbrechen',exact:true}).click();if(!(await call('/projects/'+project.id+'/use-cases')).length)throw Error('Cancel removed definition');
 await panel.getByRole('button',{name:'Löschen',exact:true}).click();await panel.getByRole('button',{name:'Endgültig löschen',exact:true}).click();await panel.getByRole('heading',{name:'Dein erster Use Case',exact:true}).waitFor();
 if((await call('/projects/'+project.id+'/use-cases')).length)throw Error('Use Case delete failed');if(errors.length)throw Error(errors.join('\n'));
 console.log('Use Cases UX passed: standalone navigation order, global overview/search, canonical links/reload, legacy redirect, builder, typed form, BI, ordered safe CSV, actual XLSX, wizard, zero text value, immutable revisions, reload, 320/390/768, delete/cancel');
}finally{if(project){try{const preview=await call('/projects/'+project.id+'/deletion');await call('/projects/'+project.id,'DELETE',{expected_state:preview.expected_state})}catch(e){console.error('Owned Use Cases fixture cleanup failed: '+e.message)}}await browser.close()}
