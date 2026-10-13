import {loginFixture} from './fixture-login.mjs';
import {chromium} from 'playwright';
import {mkdir} from 'node:fs/promises';
const base=process.env.CHAT_ARTIFACT_FIXTURE_ORIGIN||'http://127.0.0.1:18765';
if(!['http://127.0.0.1:18765','http://127.0.0.1:18767'].includes(base))throw Error('Synthetic fixtures only');
const output='../.local/browser';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto(base);await loginFixture(page);
 await page.locator('button.new').click();
 const id=await page.waitForFunction(()=>new URL(location.href).searchParams.get('chat'));const conversationId=await id.jsonValue();
 await page.getByRole('button',{name:'Arbeitsbereich öffnen',exact:true}).click();
 const work=page.getByRole('complementary',{name:'Arbeitsbereich neben dem Chat',exact:true});
 if(await work.getByLabel('Datei in Projekt speichern',{exact:true}).count())throw Error('Free chat still requires project selection');
 const create=work.getByRole('button',{name:'Neue Datei erstellen',exact:true});await create.waitFor();
 for(const [kind,format] of [['docx','Word-Dokument'],['pptx','PowerPoint-Präsentation']]){
  await create.click();const dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
  await dialog.getByRole('radio',{name:format,exact:true}).check();
  if(kind==='pptx'){await dialog.getByLabel('Gewünschtes Ergebnis',{exact:true}).fill('Erstelle fünf Folien über die synthetische Initiative Aurora.');await dialog.getByLabel('Gewünschte Folienanzahl',{exact:true}).fill('5');await dialog.getByRole('button',{name:'Lokal entwerfen',exact:true}).click();await dialog.getByText('Lokaler Entwurf bereit',{exact:false}).waitFor();if(await dialog.getByLabel('Folientitel',{exact:true}).count()!==5)throw Error('Free chat draft lost requested five slides');}
  await dialog.getByRole('button',{name:'Inhalt selbst eingeben',exact:true}).click();
  await dialog.getByLabel('Dateititel',{exact:true}).fill('Synthetisches Aurora '+kind);
  if(kind==='docx')await dialog.getByLabel('Dokumenttext',{exact:true}).fill('Ausschließlich synthetischer Arbeitsauftrag für Projekt Aurora.');
  else {await dialog.getByLabel('Folientitel',{exact:true}).first().fill('Aurora Überblick');await dialog.getByLabel('Stichpunkte',{exact:true}).first().fill('Fiktive Ziele\nFiktive nächste Schritte');}
  await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();
  const row=work.locator('article.citation').filter({hasText:'Synthetisches Aurora '+kind});await row.getByRole('button',{name:'Vorschau öffnen',exact:true}).click();
  const preview=page.getByRole('dialog',{name:'Dateivorschau',exact:true});
  if(!await preview.getByRole('button',{name:'Diese Dateiversion freigeben',exact:true}).isDisabled())throw Error('Review bypass');
  const earlyDownload=preview.getByRole('link',{name:'Datei herunterladen',exact:true});await earlyDownload.waitFor();
  const fileEvent=page.waitForEvent('download');await earlyDownload.click();const file=await fileEvent;if(!file.suggestedFilename().endsWith('.'+kind)||await file.failure())throw Error('Ready unreviewed file did not download');
  const rows=await page.evaluate(async id=>(await fetch('/api/conversations/'+id+'/artifacts')).json(),conversationId);if(rows.find(value=>value.spec.plan.title==='Synthetisches Aurora '+kind).accepted)throw Error('Download falsely recorded human acceptance');
  await preview.getByLabel('Ich habe alle Vorschauseiten geprüft.',{exact:true}).check();await preview.getByRole('button',{name:'Diese Dateiversion freigeben',exact:true}).click();
  const download=row.getByRole('link',{name:'Datei herunterladen',exact:true});await download.waitFor();
  if(!(await download.getAttribute('href')).startsWith('/api/conversations/'+conversationId+'/artifacts/'))throw Error('Download owner incorrect');
 }
 await page.reload();await work.getByText('Synthetisches Aurora pptx · Version 1',{exact:true}).waitFor();
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:output+'/chat-files-mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2))throw Error('Mobile horizontal overflow');
 if(errors.length)throw Error(errors.join('\n'));console.log('Free chat Word/PowerPoint ownership, preview review, download, reload and mobile passed.');
}finally{await browser.close()}
