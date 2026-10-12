import {loginFixture} from './fixture-login.mjs';
// Focused synthetic UI check. Actual Office layout has a separate offline smoke.
import {chromium} from 'playwright';
import {mkdir,readFile} from 'node:fs/promises';
const base=process.env.ARTIFACT_FIXTURE_ORIGIN||'http://127.0.0.1:18765';
if(!['http://127.0.0.1:18765','http://127.0.0.1:18767'].includes(base))throw Error('Synthetic fixtures only');
const output='../.local/browser';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:390,height:844}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto(base);
 await loginFixture(page);
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 await page.getByRole('button',{name:'Projekte',exact:true}).click();
 await page.getByRole('button',{name:'Neues Projekt',exact:true}).click();
 const name='Synthetic artifact version test '+Date.now();
 await page.getByLabel('Projektname',{exact:true}).fill(name);
 await page.getByRole('button',{name:'Projektraum erstellen',exact:true}).click();
 await page.getByRole('tab',{name:'Erstellte Dateien',exact:true}).click();
 await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
 let dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
 await dialog.getByLabel('Dateititel',{exact:true}).fill('Synthetic word version');
 await dialog.getByLabel('Dokumenttext',{exact:true}).fill('Editable synthetic original text.');
 await dialog.getByRole('button',{name:'Mit KI entwerfen',exact:true}).click();
 await dialog.getByLabel('Gewünschtes Ergebnis',{exact:true}).fill('Synthetic preserved goal');
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
 if(await dialog.getByLabel('Dokumenttext',{exact:true}).inputValue()!=='Editable synthetic original text.')throw Error('Mode switch lost manual content');
 await dialog.getByRole('button',{name:'Mit KI entwerfen',exact:true}).click();
 if(await dialog.getByLabel('Gewünschtes Ergebnis',{exact:true}).inputValue()!=='Synthetic preserved goal')throw Error('Mode switch lost goal');
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
 await dialog.getByText('Tabellen, Bilder und Abschnittsoptionen',{exact:true}).click();
 await dialog.getByRole('button',{name:'Tabelle hinzufügen',exact:true}).click();
 for(const [i,value]of ['Column A','Column B','Alpha','42'].entries())await dialog.locator('fieldset fieldset input').nth(i).fill(value);
 await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
 await page.getByRole('button',{name:'Vorschau öffnen',exact:true}).click();
 const preview=page.getByRole('dialog',{name:'Dateivorschau',exact:true});
 await preview.getByLabel('Ich habe alle Vorschauseiten geprüft.',{exact:true}).check();
 await preview.getByRole('button',{name:'Diese Dateiversion freigeben',exact:true}).click();
 await page.getByRole('link',{name:'Datei herunterladen',exact:true}).first().waitFor();
 await page.reload();
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 await page.getByRole('button',{name:'Projekte',exact:true}).click();
 await page.getByRole('heading',{name,exact:true}).locator('..').click();
 await page.getByRole('tab',{name:'Erstellte Dateien',exact:true}).click();
 await page.getByRole('link',{name:'Datei herunterladen',exact:true}).first().waitFor();
 await page.getByRole('button',{name:'Neue Version bearbeiten',exact:true}).click();
 dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
 if(await dialog.getByLabel('Dokumenttext',{exact:true}).inputValue()!=='Editable synthetic original text.')throw Error('Version lost its editable text');
 if(await dialog.locator('fieldset fieldset input').nth(3).inputValue()!=='42')throw Error('Version lost editable table');
 await dialog.getByLabel('Dateititel',{exact:true}).fill('Synthetic word version two');
 await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
 await page.getByText('Synthetic word version two · Version 2',{exact:true}).waitFor();
 await page.waitForFunction(()=>[...document.querySelectorAll('a')].filter(a=>a.textContent==='Datei herunterladen').length===2); // Both validated versions download without claiming human review.
 await page.getByRole('tab',{name:/Quellen ·/}).click();
 await page.locator('input[type=file]').setInputFiles([
  {name:'synthetic-artifact.pdf',mimeType:'application/pdf',buffer:await readFile(output+'/artifact-input.pdf')},
  {name:'synthetic-artifact.png',mimeType:'image/png',buffer:await readFile(output+'/artifact-input.png')}
 ]);
 await page.waitForFunction(()=>document.querySelectorAll('.source-list li').length===2); // Raw Office/PDF/image inputs do not require OCR in this UI fixture.
 await page.getByRole('tab',{name:'Erstellte Dateien',exact:true}).click();
 // Persist manual work across reload; reject a stale recorded source revision on resume.
 await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
 dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
 await dialog.getByLabel('Dateititel',{exact:true}).fill('Synthetic resumed draft');
 await dialog.getByLabel('Dokumenttext',{exact:true}).fill('Preserved across reload, no silently rebound source.');
 await dialog.getByText('Gebundene Quelldateien',{exact:true}).click();
 await dialog.getByLabel('synthetic-artifact.png',{exact:true}).check();
 await dialog.getByRole('button',{name:'Mit KI entwerfen',exact:true}).click();
 await dialog.getByLabel('Gewünschtes Ergebnis',{exact:true}).fill('Synthetic persistent goal');
 await dialog.getByRole('button',{name:'Abbrechen',exact:true}).click();
 await page.getByRole('button',{name:'Entwurf fortsetzen',exact:true}).waitFor();
 await page.evaluate(()=>{
   const key=Object.keys(sessionStorage).find(key=>key.startsWith('hub-ui-draft:artifact:'));
   const draft=JSON.parse(sessionStorage.getItem(key));draft.sourceBindings[0].revision+=1;
   sessionStorage.setItem(key,JSON.stringify(draft));
 });
 await page.reload();
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 await page.getByRole('button',{name:'Projekte',exact:true}).click();
 await page.getByRole('heading',{name,exact:true}).locator('..').click();
 await page.getByRole('tab',{name:'Erstellte Dateien',exact:true}).click();
 await page.getByRole('button',{name:'Entwurf fortsetzen',exact:true}).click();
 dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 if(await dialog.getByLabel('Dokumenttext',{exact:true}).inputValue()!=='Preserved across reload, no silently rebound source.')throw Error('Reload lost manual draft');
 await dialog.getByText('Gebundene Quelldateien',{exact:true}).click();
 if(await dialog.getByLabel('synthetic-artifact.png',{exact:true}).isChecked())throw Error('Stale source silently rebound on resume');
 await dialog.getByText('Quellen wurden geändert oder fehlen.',{exact:false}).waitFor();
 if(!await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).isDisabled())throw Error('Stale draft allowed save without replan or explicit copy');
 await dialog.getByRole('button',{name:'Mit KI entwerfen',exact:true}).click();
 if(await dialog.getByLabel('Gewünschtes Ergebnis',{exact:true}).inputValue()!=='Synthetic persistent goal')throw Error('Reload lost goal');
 await dialog.getByRole('button',{name:'Abbrechen',exact:true}).click();
 await page.getByRole('button',{name:'Entwurf verwerfen',exact:true}).click();
 for(const kind of ['pptx','pdf','image']){
  await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
  dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
  await dialog.getByRole('radio',{name:({docx:'Word-Dokument',pptx:'PowerPoint-Präsentation',pdf:'PDF-Dokument',image:'Bild / Collage'})[kind],exact:true}).check();
  const title='Synthetic '+kind+' UI artifact';
  await dialog.getByLabel('Dateititel',{exact:true}).fill(title);
  if(kind==='pptx'){
   await dialog.getByLabel('Folientitel',{exact:true}).fill('First editable slide');
   await dialog.getByLabel('Stichpunkte',{exact:true}).fill('First synthetic bullet');
   await dialog.getByRole('button',{name:'Folie hinzufügen',exact:true}).click();
   await dialog.getByLabel('Folientitel',{exact:true}).nth(1).fill('Second editable slide');
   await dialog.getByLabel('Stichpunkte',{exact:true}).nth(1).fill('Second synthetic bullet');
  }else if(kind==='pdf'){
   await dialog.getByRole('button',{name:'Ausgabeseite hinzufügen',exact:true}).click();
   await dialog.getByLabel('Seite im Original',{exact:true}).fill('2');
   await dialog.getByRole('button',{name:'Ausgabeseite hinzufügen',exact:true}).click();
   await dialog.getByRole('button',{name:'Jede Ausgabeseite als eigene PDF',exact:true}).click();
   if(!await dialog.getByLabel('Nach Ausgabeseite 1 einen neuen PDF-Teil beginnen',{exact:true}).isChecked())throw Error('Missing PDF partition');
  }else{
   await dialog.getByRole('button',{name:'Bild hinzufügen',exact:true}).click();
   await dialog.getByLabel('Bildbeschriftung',{exact:true}).fill('Synthetic blue');
   await dialog.getByText('Collagegröße und Bildformat',{exact:true}).click();
   await dialog.getByLabel('Breite je Bild (Pixel)',{exact:true}).fill('128');
   await dialog.getByLabel('Höhe je Bild (Pixel)',{exact:true}).fill('128');
  }
  await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
  const card=page.locator('article').filter({has:page.getByText(title+' · Version 1',{exact:true})});
  await card.getByRole('button',{name:'Vorschau öffnen',exact:true}).click();
  const view=page.getByRole('dialog',{name:'Dateivorschau',exact:true});
  const expected=kind==='image'?1:2;
  if(await view.locator('img').count()!==expected)throw Error('Wrong preview page count');
  await view.getByLabel('Ich habe alle Vorschauseiten geprüft.',{exact:true}).check();
  await view.getByRole('button',{name:'Diese Dateiversion freigeben',exact:true}).click();
  await card.getByRole('link',{name:kind==='pdf'?'Alle PDF-Teile als ZIP herunterladen':'Datei herunterladen',exact:true}).waitFor();
  if(kind==='pdf'){
   await card.getByRole('link',{name:/PDF-Teil 1 herunterladen/}).waitFor();
   await card.getByRole('button',{name:'Neue Version bearbeiten',exact:true}).click();
   const edit=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
   if(!await edit.getByLabel('Nach Ausgabeseite 1 einen neuen PDF-Teil beginnen',{exact:true}).isChecked())throw Error('Partition lost after reload');
   await edit.getByRole('button',{name:'Abbrechen',exact:true}).click();
  }
 }
 for(const kind of ['docx','pdf']){
  await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
  dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
  await dialog.getByRole('radio',{name:({docx:'Word-Dokument',pptx:'PowerPoint-Präsentation',pdf:'PDF-Dokument',image:'Bild / Collage'})[kind],exact:true}).check();
  if(kind==='pdf')await dialog.getByLabel('PDF erstellen aus',{exact:true}).selectOption('text');
  const title='Synthetic extended '+kind;
  await dialog.getByLabel('Dateititel',{exact:true}).fill(title);
  await dialog.getByLabel('Dokumenttext',{exact:true}).fill('Local document with a bound image.');
  await dialog.getByText('Tabellen, Bilder und Abschnittsoptionen',{exact:true}).click();
  await dialog.getByRole('button',{name:'Bild in Abschnitt einfügen',exact:true}).click();
  await dialog.getByLabel('Bildunterschrift',{exact:true}).fill('Synthetic blue image');
  if(kind==='docx')await dialog.getByLabel('Zusätzlich als PDF zum Download bereitstellen',{exact:true}).check();
  await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
  const card=page.locator('article').filter({has:page.getByText(title+' · Version 1',{exact:true})});
  await card.getByRole('button',{name:'Vorschau öffnen',exact:true}).click();
  const view=page.getByRole('dialog',{name:'Dateivorschau',exact:true});
  await view.getByLabel('Ich habe alle Vorschauseiten geprüft.',{exact:true}).check();
  await view.getByRole('button',{name:'Diese Dateiversion freigeben',exact:true}).click();
  if(kind==='docx')await card.getByRole('link',{name:'Zusätzliches PDF herunterladen',exact:true}).waitFor();
  await card.getByRole('button',{name:'Neue Version bearbeiten',exact:true}).click();
  dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
  if(await dialog.getByLabel('Bildunterschrift',{exact:true}).inputValue()!=='Synthetic blue image')throw Error('Bound image/caption lost in version editor');
  await dialog.getByRole('button',{name:'Abbrechen',exact:true}).click();
 }
 for(const kind of ['pdf','image']){
  await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
  dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
  await dialog.getByRole('radio',{name:({docx:'Word-Dokument',pptx:'PowerPoint-Präsentation',pdf:'PDF-Dokument',image:'Bild / Collage'})[kind],exact:true}).check();
  await dialog.getByText('Gebundene Quelldateien',{exact:true}).click();
  await dialog.getByLabel('synthetic-artifact.'+(kind==='pdf'?'pdf':'png'),{exact:true}).check();
  await dialog.getByText('Mit dem lokalen Modell entwerfen',{exact:true}).click();
  await dialog.getByLabel('Gewünschtes Ergebnis',{exact:true}).fill(kind==='pdf'?'Output page 2 rotated 90 degrees.':'Crop the right half and resize to 128 pixels.');
  await dialog.getByRole('button',{name:'Lokal entwerfen',exact:true}).click();
  await dialog.getByText('Lokaler Entwurf bereit',{exact:false}).waitFor();
  if(kind==='pdf'&&await dialog.getByLabel('Seite im Original',{exact:true}).inputValue()!=='2')throw Error('Page operation not editable');
  if(kind==='image'&&await dialog.getByLabel('Linker Rand (%)',{exact:true}).inputValue()!=='50')throw Error('Crop operation not editable');
  await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
  await page.getByText('Synthetic local '+(kind==='pdf'?'PDF':'image')+' operation · Version 1',{exact:true}).waitFor();
 }
 for(const kind of ['docx','pptx']){
  await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
  dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
  await dialog.getByRole('radio',{name:({docx:'Word-Dokument',pptx:'PowerPoint-Präsentation',pdf:'PDF-Dokument',image:'Bild / Collage'})[kind],exact:true}).check();
  await dialog.getByText('Mit dem lokalen Modell entwerfen',{exact:true}).click();
  await dialog.getByLabel('Gewünschtes Ergebnis',{exact:true}).fill('Create an editable synthetic local draft.');
  if(kind==='pptx')await dialog.getByLabel('Gewünschte Folienanzahl',{exact:true}).fill('2');
  await dialog.getByRole('button',{name:'Lokal entwerfen',exact:true}).click();
  await dialog.getByText('Lokaler Entwurf bereit',{exact:false}).waitFor();
  if(kind==='docx'&&await dialog.getByLabel('Dokumenttext',{exact:true}).inputValue()!=='Editable synthetic draft text.')throw Error('Local draft did not populate editor');
  if(kind==='pptx'&&await dialog.getByLabel('Folientitel',{exact:true}).count()!==2)throw Error('Requested slide count lost');
  await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
  await page.getByText(kind==='docx'?'Synthetic local document draft · Version 1':'Synthetic local presentation draft · Version 1',{exact:true}).waitFor();
 }
 await page.getByRole('tab',{name:/Gespräche ·/}).click();
 await page.getByRole('button',{name:'Neues Projektgespräch',exact:true}).click();
 await page.getByLabel('Nachricht',{exact:true}).fill('Erstelle eine Word-Datei. SYNTHETIC_FILE_REQUEST');
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
 await page.getByRole('button',{name:'Datei im Arbeitsbereich öffnen',exact:true}).waitFor();
 const inlineFile=page.locator('.messages article.citation').filter({has:page.getByRole('button',{name:'Datei im Arbeitsbereich öffnen',exact:true})});await inlineFile.getByRole('link',{name:'Datei herunterladen',exact:true}).waitFor();
 await page.getByRole('button',{name:'Datei im Arbeitsbereich öffnen',exact:true}).click();
 await page.getByRole('complementary',{name:'Arbeitsbereich neben dem Chat',exact:true}).waitFor();
 await page.getByText('Synthetic local document draft · Version 1',{exact:true}).first().waitFor();
 await page.getByRole('dialog',{name:'Dateivorschau',exact:true}).getByRole('button',{name:'Schließen',exact:true}).click();
 await page.getByRole('button',{name:'Arbeitsbereich schließen',exact:true}).click();
 await page.getByRole('button',{name:name+' · Projektraum öffnen',exact:true}).click();
 await page.getByRole('tab',{name:/Gespräche ·/}).click();
 await page.getByRole('button',{name:'Neues Projektgespräch',exact:true}).click();
 await page.getByLabel('Nachricht',{exact:true}).fill('Recherchiere und erstelle eine Word-Datei. SYNTHETIC_FILE_REQUEST SYNTHETIC_WEB_QUERY');
 await page.getByRole('button',{name:'Websuche aktiviert',exact:true}).waitFor();
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
 await page.getByRole('button',{name:'Datei im Arbeitsbereich öffnen',exact:true}).waitFor();
 await page.getByRole('button',{name:'Datei im Arbeitsbereich öffnen',exact:true}).click();
 await page.getByRole('dialog',{name:'Dateivorschau',exact:true}).getByRole('button',{name:'Schließen',exact:true}).click();
 const researchCard=page.locator('article').filter({hasText:'Synthetic local document draft · Version 1'}).filter({hasText:'Verwendete Websuchauszüge'});
 await researchCard.locator('summary').click();
 await researchCard.getByText('Verwendete Websuchauszüge · lokal verarbeitet',{exact:true}).waitFor();
 if(!(await researchCard.innerText()).includes('https://example.org/synthetic-source'))throw Error('Search citation missing in file provenance');
 await page.getByRole('button',{name:'Arbeitsbereich schließen',exact:true}).click();
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 await Promise.all([page.waitForResponse(response=>response.url().includes('/api/conversations?q=')&&response.request().method()==='GET'),page.locator('button.new').click()]);
 await page.getByLabel('Nachricht',{exact:true}).fill('A synthetic short answer for Word export.');
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
 await page.getByRole('button',{name:'Chatantwort als Datei übernehmen',exact:true}).waitFor();
 await page.getByRole('button',{name:'Chatantwort als Datei übernehmen',exact:true}).click();
 if(await page.getByLabel(/Datei in Projekt speichern/).count())throw Error('Free chat export still requires a project');
 await page.getByRole('button',{name:'Chatantwort als Word übernehmen',exact:true}).click();
 dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
 if(!(await dialog.getByLabel('Dokumenttext',{exact:true}).inputValue()).length)throw Error('Chat export lost content');
 await dialog.getByText('Mit dem lokalen Modell entwerfen',{exact:true}).click();
 await dialog.getByLabel('Gewünschtes Ergebnis',{exact:true}).fill('Create a short Word section from the selected answer.');
 await dialog.getByRole('button',{name:'Lokal entwerfen',exact:true}).click();
 await dialog.getByText('Lokaler Entwurf bereit',{exact:false}).waitFor();
 await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
 await page.getByText('Aus Chatantwort · Revision 1 · lokal gespeichert',{exact:true}).waitFor();
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile artifact overflow');
 await page.screenshot({path:output+'/artifact-version-mobile.png',fullPage:true,animations:'disabled'});
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Synthetic artifact UI passed: review, download, reload, editable version, old version retained, all four formats, local draft forms, chat export, mobile.');
}catch(e){
 await page.screenshot({path:output+'/artifact-focused-failure.png',fullPage:true});
 console.error('Visible state:',await page.locator('body').innerText());
 console.error('Runtime errors:',errors);
 throw e;
}finally{await browser.close()}
await import('./artifact-skills-check.mjs');
