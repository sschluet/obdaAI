// Focused synthetic UI check. Actual Office layout has a separate offline smoke.
import {chromium} from 'playwright';
import {mkdir,readFile} from 'node:fs/promises';
const output='../.local/browser';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:390,height:844}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('http://127.0.0.1:18765');
 await page.getByLabel('Passwort',{exact:true}).fill('synthetic-ui-password');
 await page.getByRole('button',{name:'Anmelden',exact:true}).click();
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 await page.getByRole('button',{name:'Projekte',exact:true}).click();
 await page.getByRole('button',{name:'Neues Projekt',exact:true}).click();
 const name='Synthetic artifact version test '+Date.now();
 await page.getByLabel('Projektname',{exact:true}).fill(name);
 await page.getByRole('button',{name:'Projektraum erstellen',exact:true}).click();
 await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
 let dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByLabel('Dateititel',{exact:true}).fill('Synthetic word version');
 await dialog.getByLabel('Dokumenttext',{exact:true}).fill('Editable synthetic original text.');
 await dialog.getByRole('button',{name:'Tabelle hinzufügen',exact:true}).click();
 for(const [i,value]of ['Column A','Column B','Alpha','42'].entries())await dialog.locator('fieldset fieldset input').nth(i).fill(value);
 await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
 await page.getByRole('button',{name:'Vorschau öffnen',exact:true}).click();
 const preview=page.getByRole('dialog',{name:'Dateivorschau',exact:true});
 await preview.getByLabel('Ich habe alle Vorschauseiten geprüft.',{exact:true}).check();
 await preview.getByRole('button',{name:'Diese Dateiversion freigeben',exact:true}).click();
 await page.getByRole('link',{name:'Datei herunterladen',exact:true}).waitFor();
 await page.reload();
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 await page.getByRole('button',{name:'Projekte',exact:true}).click();
 await page.getByRole('button',{name,exact:true}).click();
 await page.getByRole('link',{name:'Datei herunterladen',exact:true}).waitFor();
 await page.getByRole('button',{name:'Neue Version bearbeiten',exact:true}).click();
 dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 if(await dialog.getByLabel('Dokumenttext',{exact:true}).inputValue()!=='Editable synthetic original text.')throw Error('Version lost its editable text');
 if(await dialog.locator('fieldset fieldset input').nth(3).inputValue()!=='42')throw Error('Version lost editable table');
 await dialog.getByLabel('Dateititel',{exact:true}).fill('Synthetic word version two');
 await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
 await page.getByText('Synthetic word version two · Version 2',{exact:true}).waitFor();
 if(await page.getByRole('link',{name:'Datei herunterladen',exact:true}).count()!==1)throw Error('Old file lost or new version bypassed review');
 await page.locator('input[type=file]').setInputFiles([
  {name:'synthetic-artifact.pdf',mimeType:'application/pdf',buffer:await readFile(output+'/artifact-input.pdf')},
  {name:'synthetic-artifact.png',mimeType:'image/png',buffer:await readFile(output+'/artifact-input.png')}
 ]);
 for(const kind of ['pptx','pdf','image']){
  await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
  dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
  await dialog.getByLabel('Dateiformat',{exact:true}).selectOption(kind);
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
  }else{
   await dialog.getByRole('button',{name:'Bild hinzufügen',exact:true}).click();
   await dialog.getByLabel('Bildbeschriftung',{exact:true}).fill('Synthetic blue');
   await dialog.getByLabel('Breite je Bild (Pixel)',{exact:true}).fill('128');
   await dialog.getByLabel('Höhe je Bild (Pixel)',{exact:true}).fill('128');
  }
  await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
  const card=page.locator('article').filter({has:page.getByText(title+' · Version 1',{exact:true})});
  await card.getByRole('button',{name:'Vorschau öffnen',exact:true}).click();
  const view=page.getByRole('dialog',{name:'Dateivorschau',exact:true});
  const expected=kind==='pptx'?2:1;
  if(await view.locator('img').count()!==expected)throw Error('Wrong preview page count');
  await view.getByLabel('Ich habe alle Vorschauseiten geprüft.',{exact:true}).check();
  await view.getByRole('button',{name:'Diese Dateiversion freigeben',exact:true}).click();
  await card.getByRole('link',{name:'Datei herunterladen',exact:true}).waitFor();
 }
 for(const kind of ['docx','pdf']){
  await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
  dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
  await dialog.getByLabel('Dateiformat',{exact:true}).selectOption(kind);
  if(kind==='pdf')await dialog.getByLabel('PDF erstellen aus',{exact:true}).selectOption('text');
  const title='Synthetic extended '+kind;
  await dialog.getByLabel('Dateititel',{exact:true}).fill(title);
  await dialog.getByLabel('Dokumenttext',{exact:true}).fill('Local document with a bound image.');
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
  if(await dialog.getByLabel('Bildunterschrift',{exact:true}).inputValue()!=='Synthetic blue image')throw Error('Bound image/caption lost in version editor');
  await dialog.getByRole('button',{name:'Abbrechen',exact:true}).click();
 }
 for(const kind of ['docx','pptx']){
  await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
  dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
  await dialog.getByLabel('Dateiformat',{exact:true}).selectOption(kind);
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
 await page.getByRole('button',{name:'Mit diesen Dokumenten chatten',exact:true}).click();
 await page.getByLabel('Nachricht',{exact:true}).fill('Erstelle eine Word-Datei. SYNTHETIC_FILE_REQUEST');
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
 await page.getByRole('button',{name:'Datei im Projekt öffnen',exact:true}).waitFor();
 await page.getByRole('button',{name:'Datei im Projekt öffnen',exact:true}).click();
 await page.getByRole('heading',{name,exact:true}).waitFor();
 await page.getByText('Synthetic local document draft · Version 1',{exact:true}).first().waitFor();
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 await page.locator('button.new').click();
 await page.getByLabel('Nachricht',{exact:true}).fill('A synthetic short answer for Word export.');
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
 await page.getByRole('button',{name:'Chatantwort als Datei übernehmen',exact:true}).waitFor();
 await page.getByRole('button',{name:'Chatantwort als Datei übernehmen',exact:true}).click();
 await page.getByRole('button',{name,exact:true}).click();
 await page.getByRole('button',{name:'Chatantwort als Word übernehmen',exact:true}).click();
 dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 if(!(await dialog.getByLabel('Dokumenttext',{exact:true}).inputValue()).length)throw Error('Chat export lost content');
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
