import {loginFixture} from './fixture-login.mjs';
// Capture the real UI against an isolated synthetic fixture, never a live deployment.
import {chromium} from 'playwright';
import {mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const base=process.env.SHOWCASE_FIXTURE_ORIGIN||'http://127.0.0.1:18767';
if(base!=='http://127.0.0.1:18767')throw Error('Only the dedicated synthetic fixture is permitted');
const output=fileURLToPath(new URL('../website/assets/',import.meta.url));await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:980},deviceScaleFactor:1});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
// Synthetic endpoint only: the public screenshot never displays internal addresses.
await page.route('**/api/web-settings',async route=>{if(route.request().method()!=='GET'){await route.continue();return;}const response=await route.fetch();const settings=await response.json();await route.fulfill({response,json:{...settings,endpoint:'https://search.example.org/search'}});});
const capture=async name=>{await page.screenshot({path:output+'/'+name+'.png',animations:'disabled',fullPage:name==='websettings'});};
try{
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.goto(base);
 await loginFixture(page);
 await page.getByRole('button',{name:'Ideen werden Ergebnisse',exact:true}).click();
 await page.getByText('Ein klarer Plan für Projekt Aurora',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Antwortvorgaben öffnen',exact:true}).click();
 await page.getByRole('radiogroup',{name:'Antwortlänge',exact:true}).waitFor();
 await capture('chat');
 await page.getByRole('button',{name:'Arbeitsbereich schließen',exact:true}).click();
 await page.getByRole('button',{name:'Projekte',exact:true}).click();
 await page.getByRole('heading',{name:'Projekt Aurora',exact:true}).locator('..').click();
 await page.getByRole('tab',{name:/Quellen ·/}).click();
 if(!await page.getByText('Projektueberblick.md',{exact:true}).count())await page.locator('input[type=file]').setInputFiles([
  {name:'Projektueberblick.md',mimeType:'text/markdown',buffer:Buffer.from('# Projekt Aurora\nEin synthetisches Beispiel für eine lokale Wissensbasis.\nZiel: Ideen aus Quellen in überprüfbare Ergebnisse verwandeln.')},
  {name:'Meilensteine.csv',mimeType:'text/csv',buffer:Buffer.from('Phase;Ziel\nEntdecken;Quellen sammeln\nVerstehen;Fragen beantworten\nGestalten;Dateien erstellen')}
 ]);
 await page.getByText('Projektueberblick.md',{exact:true}).waitFor();await page.getByText('Meilensteine.csv',{exact:true}).waitFor();await page.getByText('Bereit',{exact:true}).first().waitFor();
 await capture('projects');
 await page.getByRole('tab',{name:'Erstellte Dateien',exact:true}).click();
 await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});
 await dialog.getByLabel('Gewünschtes Ergebnis',{exact:true}).fill('Erstelle eine kurze Projektübersicht mit Ziel, offenen Fragen und drei nächsten Schritten. Verwende eine klare, sachliche Gliederung.');
 await capture('files');
 await dialog.getByRole('button',{name:'Abbrechen',exact:true}).click();
 await page.getByRole('button',{name:'Aufgaben',exact:true}).click();
 const add=page.getByRole('button',{name:'Beispielaufgaben hinzufügen',exact:true});
 await add.waitFor();
 if(!await page.getByRole('heading',{name:'Beispiel: Arbeitsraumüberblick',exact:true}).count())await add.click();
 await page.getByRole('heading',{name:'Beispiel: Arbeitsraumüberblick',exact:true}).waitFor();
 await page.getByRole('button',{name:'Neue Aufgabe',exact:true}).click();
 const task=page.getByRole('dialog',{name:'Aufgabe bearbeiten',exact:true});
 await task.getByLabel('Name der Aufgabe',{exact:true}).fill('Projekt Aurora · Wochenüberblick');
 await task.getByLabel('Was soll erledigt werden?',{exact:true}).fill('Fasse den aktuellen Projektstand zusammen und nenne die nächsten Schritte.');
 await capture('tasks');
 await task.getByRole('button',{name:'Schließen',exact:true}).click();
 await Promise.all([page.waitForResponse(response=>response.url().endsWith('/api/knowledge-sources')&&response.request().method()==='GET'&&response.status()===200),page.getByRole('button',{name:'Wissen',exact:true}).click()]);
 await page.getByRole('heading',{name:'Deine Wissensquellen',exact:true}).waitFor();
 if(!await page.getByRole('heading',{name:'Demo · Dokumentenarchiv',exact:true}).count()){
  await page.getByRole('button',{name:'Wissensquelle hinzufügen',exact:true}).click();
  const source=page.getByRole('dialog',{name:'Wissensquelle konfigurieren',exact:true});
  await source.getByLabel('Name',{exact:true}).fill('Demo · Dokumentenarchiv');
  await source.getByLabel('Server oder IP-Adresse',{exact:true}).fill('192.0.2.10');
  await source.getByLabel('Freigabename',{exact:true}).fill('Beispieldokumente');
  await source.getByLabel('Benutzername',{exact:true}).fill('demo');
  await source.getByLabel('Passwort',{exact:true}).fill('synthetic-ui-source-password');
  await source.getByRole('button',{name:'Quelle speichern',exact:true}).click();await source.waitFor({state:'hidden'});
 }
 await page.getByRole('heading',{name:'Demo · Dokumentenarchiv',exact:true}).waitFor();
 await capture('knowledge');
 await page.getByRole('button',{name:'Chat',exact:true}).click();
 await page.getByRole('button',{name:'Ideen werden Ergebnisse',exact:true}).click();
 await page.setViewportSize({width:390,height:844});
 await capture('mobile');
 await page.setViewportSize({width:1440,height:980});await page.getByRole('button',{name:'Einstellungen',exact:true}).click();await page.getByRole('button',{name:'Sicherheit',exact:true}).click();await page.getByRole('heading',{name:'Passwort ändern',exact:true}).waitFor();await capture('security');
 await page.setViewportSize({width:1440,height:1520});await page.getByRole('button',{name:'Webrecherche',exact:true}).click();await page.getByRole('heading',{name:'Suchdienst und Ergebnisse',exact:true}).waitFor();await page.getByRole('radio',{name:'Alle Sprachen',exact:true}).waitFor();await capture('websettings');await page.setViewportSize({width:1440,height:980});
 await page.getByRole('button',{name:'Neues Gespräch',exact:true}).click();await page.getByLabel('Nachricht',{exact:true}).fill('Ein rein synthetisches Beispiel: Zeige eine kurze Antwort mit Herkunftshinweis.');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await page.getByText('Antwort abgeschlossen',{exact:true}).waitFor();await page.locator('.answer-processing').filter({hasText:'Lokal · synthetic-fixture'}).waitFor();await capture('processing');
 await page.getByRole('button',{name:'Arbeitsraum durchsuchen',exact:true}).click();const search=page.getByRole('dialog',{name:'Suchen und weiterarbeiten',exact:true});await search.getByRole('combobox').fill('Projekt');await search.getByRole('option').first().waitFor();await capture('search');await search.getByRole('button',{name:'Suche schließen',exact:true}).click();
 if(errors.length)throw Error(errors.join('\n'));
 // A stored synthetic long answer illustrates detached reading; never open real chats.
 const csrf=(await (await page.request.get(base+'/api/me')).json()).csrf;
 const created=await page.request.post(base+'/api/conversations',{headers:{'X-CSRF-Token':csrf,Origin:base},data:{cloud_allowed:false}});
 if(!created.ok())throw Error('Synthetic reading conversation could not be created');
 const reading=await created.json();
 const sections=[
 ['Ein gemeinsamer Ausgangspunkt','Projekt Aurora bündelt Ideen, Quellen und nächste Schritte in einem persönlichen Arbeitsraum. Ein klarer Überblick erleichtert den Einstieg: Was wissen wir bereits, welche Fragen sind offen und welches Ergebnis brauchen wir als Nächstes?'],
 ['Erst verstehen, dann entscheiden','Eine gute Recherche ordnet Informationen ein. Wir halten Annahmen sichtbar, vergleichen Perspektiven und unterscheiden gesicherte Aussagen von offenen Fragen. So entsteht ein nachvollziehbarer Weg von den ersten Notizen zu einer belastbaren Entscheidung.'],
 ['In deinem Tempo lesen','Lange Antworten dürfen in Ruhe gelesen werden. Wenn du zu einem früheren Abschnitt zurückgehst, bleibt deine Leseposition erhalten. Der Text kann weiter wachsen, während du einen Gedanken prüfst. Über „Zum Ende“ kehrst du direkt zum neuesten Abschnitt zurück.'],
 ['Aus Wissen werden nächste Schritte','Wir führen die Ergebnisse in einer kurzen Übersicht zusammen: Ziel, wichtigste Erkenntnisse, offene Fragen und konkrete nächste Schritte. Ein kleiner, klarer nächster Schritt ist hilfreicher als eine lange Liste ohne Reihenfolge.']
 ];
 const longText='## Ein klarer Blick auf Projekt Aurora\n\n*Synthetischer Beispieltext zur Illustration der Leseposition.*\n\n'+Array.from({length:12},(_,i)=>'### '+(i+1)+'. '+sections[i%sections.length][0]+'\n\n'+sections[i%sections.length][1]+'\n\n').join('');
 await page.route('**/api/conversations/'+reading.id,async route=>{if(route.request().method()!=='GET'){await route.continue();return}await route.fulfill({json:{...reading,title:'Projekt Aurora · Gedanken in Ruhe lesen',title_status:'succeeded',messages:[{id:'synthetic-reading-user',role:'user',content:'Zeige mir eine ausführliche Übersicht zu unserem Beispielprojekt Aurora.',label:'LOCAL_ONLY'},{id:'synthetic-reading-answer',role:'assistant',content:longText,label:'LOCAL_ONLY',processing:{run_id:'synthetic-reading-run',provider:'local',model:'synthetic-fixture',model_used:true,status:'succeeded'}}],runs:[]}});});
 await page.goto(base+'/?view=Chat&chat='+reading.id);
 await page.getByRole('heading',{name:'Ein klarer Blick auf Projekt Aurora',exact:true}).waitFor();
 await page.locator('.chat-scroll').hover();await page.mouse.wheel(0,-10000);
 await page.getByRole('button',{name:'Zum Ende',exact:true}).waitFor();
 await capture('chatreading');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Eleven gallery screenshots plus mobile captured with synthetic data only.');
}finally{await browser.close();}
