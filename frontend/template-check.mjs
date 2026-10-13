// Isolated synthetic fixture only: templates, replacement consent and real API payloads.
import {chromium} from 'playwright';
import {mkdir} from 'node:fs/promises';
import {loginFixture} from './fixture-login.mjs';
const output='../.local/browser';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:390,height:844}});
const errors=[],draftRequests=[],saveRequests=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('request',request=>{if(request.method()!=='POST')return;
 if(/\/artifact-drafts$/.test(request.url()))draftRequests.push(request.postDataJSON());
 if(/\/artifacts(?:\/[^/]+\/versions)?$/.test(request.url()))saveRequests.push(request.postDataJSON());
});
const name='Synthetic file templates '+Date.now();
const editor=()=>page.getByRole('dialog',{name:'Datei erstellen',exact:true});
const button=(label)=>editor().getByRole('button',{name:label,exact:true});
async function newFile(kind='docx'){
 await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
 await editor().getByRole('radio',{name:({docx:'Word-Dokument',pptx:'PowerPoint-Präsentation',pdf:'PDF-Dokument',image:'Bild / Collage'})[kind],exact:true}).check();
}
async function choose(id){await editor().getByRole('radio',{name:({'project-overview':'Projektübersicht','meeting-note':'Besprechungsnotiz','decision-brief':'Entscheidungsvorlage','project-status':'Projektstatus'})[id],exact:true}).check();await button('Gliederung einsetzen').click();}
async function replace(){await button('Entwurfsinhalt durch leere Gliederung ersetzen').click();}
async function fillWord(text){const fields=editor().getByLabel('Dokumenttext',{exact:true});for(let i=0;i<await fields.count();i++)await fields.nth(i).fill(text+' '+(i+1));}
try{
 await page.goto('http://127.0.0.1:18765');await loginFixture(page);
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 await page.getByRole('button',{name:'Projekte',exact:true}).click();
 await page.getByRole('button',{name:'Neues Projekt',exact:true}).click();
 await page.getByLabel('Projektname',{exact:true}).fill(name);
 await page.getByRole('button',{name:'Projektraum erstellen',exact:true}).click();
 await page.getByRole('tab',{name:'Erstellte Dateien',exact:true}).click();
 await newFile();await choose('project-overview');
 if(await button('Entwurfsinhalt durch leere Gliederung ersetzen').count())throw Error('Blank draft unexpectedly needs replacement consent');
 const headings=await editor().getByLabel('Abschnittsüberschrift',{exact:true}).evaluateAll(nodes=>nodes.map(node=>node.value));
 if(headings.join('|')!=='Ziel und Umfang|Aktueller Stand|Risiken und offene Fragen|Nächste Schritte')throw Error('Project template headings differ');
 if((await editor().getByLabel('Dokumenttext',{exact:true}).evaluateAll(nodes=>nodes.map(node=>node.value))).some(Boolean))throw Error('Template invented content');
 await editor().getByLabel('Dokumenttext',{exact:true}).first().fill('Synthetic user content that must survive declining replacement.');
 await choose('meeting-note');await button('Inhalt behalten').click();
 if(!(await editor().getByLabel('Dokumenttext',{exact:true}).first().inputValue()).includes('must survive'))throw Error('Declining replacement lost content');
 await button('Gliederung einsetzen').click();await replace();
 if(await editor().getByLabel('Abschnittsüberschrift',{exact:true}).first().inputValue()!=='Anlass und Teilnehmende')throw Error('Meeting template not applied');
 await choose('decision-brief');await replace();
 if(await editor().getByLabel('Abschnittsüberschrift',{exact:true}).first().inputValue()!=='Entscheidungsfrage')throw Error('Decision template not applied');
 await button('Vorlagenziel in KI-Auftrag übernehmen').click();
 const goal=await editor().getByLabel('Gewünschtes Ergebnis',{exact:true}).inputValue();
 if(!goal.includes('Entscheidungsvorlage')||!goal.includes('Erfinde keine'))throw Error('Template goal has no effect or missing evidence constraint');
 await button('Vorlagenziel in KI-Auftrag übernehmen').click();
 if(await editor().getByLabel('Gewünschtes Ergebnis',{exact:true}).inputValue()!==goal)throw Error('Repeated goal application duplicated prompt');
 await button('Lokal entwerfen').click();await editor().getByText('Lokaler Entwurf bereit',{exact:false}).waitFor();
 if(draftRequests.at(-1)?.goal!==goal)throw Error('Template goal did not reach draft API');
 await choose('project-overview');await replace();await fillWord('Synthetic verified project text');
 const first='Synthetic template Word '+Date.now();await editor().getByLabel('Dateititel',{exact:true}).fill(first);
 await button('Datei und Vorschau erstellen').click();await page.getByText(first+' · Version 1',{exact:true}).waitFor();
 if(saveRequests.at(-1).draft_token)throw Error('Replaced template reused model receipt');
 if(saveRequests.at(-1).spec.plan.sections.length!==4)throw Error('Applied template was not saved');
 let card=page.locator('article').filter({has:page.getByText(first+' · Version 1',{exact:true})});
 await card.getByRole('link',{name:'Datei herunterladen',exact:true}).waitFor(); // Validated native files download without pretending human review.
 await card.getByRole('button',{name:'Neue Version bearbeiten',exact:true}).click();await choose('meeting-note');
 if(!await button('Entwurfsinhalt durch leere Gliederung ersetzen').isVisible())throw Error('Version replacement lacks consent');
 await replace();await fillWord('Synthetic meeting content');const second=first+' revised';
 await editor().getByLabel('Dateititel',{exact:true}).fill(second);await button('Datei und Vorschau erstellen').click();
 await page.getByText(second+' · Version 2',{exact:true}).waitFor();
 if(saveRequests.at(-1).expected_revision!==1)throw Error('Template lost optimistic version guard');
 await page.getByText(first+' · Version 1',{exact:true}).waitFor();
 await newFile('pptx');await choose('project-status');
 if(await editor().getByLabel('Folientitel',{exact:true}).count()!==4)throw Error('PPT template does not have four slides');
 const bullets=editor().getByLabel('Stichpunkte',{exact:true});
 for(let i=0;i<4;i++){if(await bullets.nth(i).inputValue())throw Error('PPT template invented bullet facts');await bullets.nth(i).fill('Synthetic verified status '+(i+1));}
 const ppt='Synthetic template PowerPoint '+Date.now();await editor().getByLabel('Dateititel',{exact:true}).fill(ppt);
 await button('Datei und Vorschau erstellen').click();await page.getByText(ppt+' · Version 1',{exact:true}).waitFor();
 card=page.locator('article').filter({has:page.getByText(ppt+' · Version 1',{exact:true})});
 await card.getByRole('button',{name:'Vorschau öffnen',exact:true}).click();
 if(await page.getByRole('dialog',{name:'Dateivorschau',exact:true}).locator('img').count()!==4)throw Error('PPT native preview does not match template');
 await page.getByRole('dialog',{name:'Dateivorschau',exact:true}).getByRole('button',{name:'Schließen',exact:true}).click();
 await newFile();await choose('decision-brief');await editor().getByLabel('Dokumenttext',{exact:true}).first().fill('Synthetic preserved template input');
 await button('Abbrechen').click();await page.reload();
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();await page.getByRole('button',{name:'Projekte',exact:true}).click();
 await page.getByRole('heading',{name,exact:true}).locator('..').click();await page.getByRole('tab',{name:'Erstellte Dateien',exact:true}).click();
 await page.getByRole('button',{name:'Entwurf fortsetzen',exact:true}).click();
 if(!await editor().getByRole('radio',{name:'Entscheidungsvorlage',exact:true}).isChecked())throw Error('Reload lost template choice');
 if(await editor().getByLabel('Dokumenttext',{exact:true}).first().inputValue()!=='Synthetic preserved template input')throw Error('Reload lost template contents');
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile template overflow');
 await page.screenshot({path:output+'/file-templates-mobile.png',fullPage:true,animations:'disabled'});
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Synthetic file templates passed: blank structures, consent, actual prompt, token invalidation, version guard, native PPT preview, reload and mobile.');
}catch(error){await page.screenshot({path:output+'/file-templates-failure.png',fullPage:true});console.error(await page.locator('body').innerText());throw error;}finally{await browser.close();}
