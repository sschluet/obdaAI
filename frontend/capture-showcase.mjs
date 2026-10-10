import {loginFixture} from './fixture-login.mjs';
// Capture the real UI against an isolated synthetic fixture, never a live deployment.
import {chromium} from 'playwright';
import {mkdir,readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const base=process.env.SHOWCASE_FIXTURE_ORIGIN||'http://127.0.0.1:18767';
if(base!=='http://127.0.0.1:18767')throw Error('Only the dedicated synthetic fixture is permitted');
const output=fileURLToPath(new URL('../website/assets/',import.meta.url));await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:980},deviceScaleFactor:1});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
// Synthetic endpoint only: the public screenshot never displays internal addresses.
const demoProfile={revision:0,enabled:true,fields:{name:'Alex Beispiel',preferred_name:'Alex',profession:'Projektleitung im fiktiven Projekt Aurora',family_status:'Fiktiver Haushalt mit einer Partnerperson',challenges:'Aufgaben priorisieren und Fokuszeiten schützen',goals:'Klare Entscheidungen und mehr Zeit für Wichtiges',interests:'Technologie, Lesen und Natur',additional_info:'Ausschließlich synthetische Angaben für diese öffentliche Illustration.'},cloud_fields:['profession']};
await page.route('**/api/personal-profile',route=>route.request().method()==='GET'?route.fulfill({json:demoProfile}):route.continue());
await page.route('**/api/web-settings',async route=>{if(route.request().method()!=='GET'){await route.continue();return;}const response=await route.fetch();const settings=await response.json();await route.fulfill({response,json:{...settings,endpoint:'https://search.example.org/search'}});});
const capture=async name=>{await page.screenshot({path:output+'/'+name+'.png',animations:'disabled',fullPage:['websettings','routing','profile'].includes(name)});};
try{
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.goto(base);
 await loginFixture(page);
 await page.getByRole('button',{name:'Ideen werden Ergebnisse',exact:true}).click();
 await page.getByText('Ein klarer Plan für Projekt Aurora',{exact:true}).waitFor();
 if(!await page.getByRole('radiogroup',{name:'Antwortlänge',exact:true}).isVisible())await page.getByRole('button',{name:'Antwortvorgaben öffnen',exact:true}).click();
 await page.getByRole('radiogroup',{name:'Antwortlänge',exact:true}).waitFor();
 await capture('chat');
 await page.getByRole('button',{name:'Arbeitsbereich schließen',exact:true}).click();
 await page.getByRole('button',{name:'Projekte',exact:true}).click();
 await page.getByRole('heading',{name:'Projekt Aurora',exact:true}).locator('..').click();
 await page.getByRole('button',{name:'Projekt bearbeiten',exact:true}).click();
 const projectEditor=page.getByRole('dialog',{name:'Projekt bearbeiten',exact:true});
 await projectEditor.getByRole('radio',{name:'KI',exact:true}).click();
 await capture('projecticons');
 await projectEditor.getByRole('button',{name:'Änderungen speichern',exact:true}).click();
 await projectEditor.waitFor({state:'hidden'});
 await page.getByRole('button',{name:'Chat',exact:true}).click();
 await page.getByRole('button',{name:'Ideen werden Ergebnisse',exact:true}).click();
 if(!await page.getByRole('radiogroup',{name:'Antwortlänge',exact:true}).isVisible())await page.getByRole('button',{name:'Antwortvorgaben öffnen',exact:true}).click();
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
 await page.setViewportSize({width:1440,height:1900});await page.getByRole('button',{name:'Routing',exact:true}).click();await page.getByRole('region',{name:'Routing-Einstellungen',exact:true}).waitFor();await page.getByLabel('Routing-Testprompt',{exact:true}).fill('Erstelle eine komplexe Recherche zu neuen Ideen für unser fiktives Projekt Aurora. Vergleiche Perspektiven und begründe die nächsten Schritte.');await page.getByRole('button',{name:'Routing prüfen',exact:true}).click();await page.getByText('Voraussichtliches Routing:',{exact:false}).waitFor();await capture('routing');await page.setViewportSize({width:1440,height:980});
 await page.setViewportSize({width:1440,height:1750});await page.getByRole('button',{name:'Über mich',exact:true}).click();await page.getByRole('region',{name:'Persönliches Profil',exact:true}).waitFor();await page.getByLabel('Name',{exact:true}).filter({visible:true}).waitFor();await capture('profile');await page.setViewportSize({width:1440,height:1080});
 const skillCsrf=(await(await page.request.get(base+'/api/me')).json()).csrf;
 const demoSkills=[{name:'Klar und kompakt',description:'Antworten klar strukturieren und auf das Wesentliche konzentrieren.',usage:'always',keywords:[],body:'Nenne zuerst das Ergebnis. Formuliere verständlich und nutze ein konkretes Beispiel.'},{name:'Gründlich recherchieren',description:'Quellen, Annahmen und nächste Schritte nachvollziehbar ordnen.',usage:'auto',keywords:['recherche'],body:'Ordne Erkenntnisse nach Fragestellung. Trenne Belege von Annahmen und nenne offene Fragen.'},{name:'Texte überarbeiten',description:'Den Text verbessern und seine Aussage bewahren.',usage:'mention',keywords:[],body:'Verbessere Aufbau und Verständlichkeit. Bewahre die Aussage und halte den gewünschten Ton.'}];
 const existingDemo=(await(await page.request.get(base+'/api/skills')).json());
 for(const demo of demoSkills){if(existingDemo.some(s=>s.name===demo.name))continue;const document='---\n'+JSON.stringify({format:'obdaai-skill-1',name:demo.name,description:demo.description,usage:demo.usage,keywords:demo.keywords,cloud_allowed:false},null,2)+'\n---\n'+demo.body;const saved=await page.request.post(base+'/api/skills',{headers:{'X-CSRF-Token':skillCsrf,Origin:base},data:{document,activate:true}});if(!saved.ok())throw Error('Synthetic skill setup failed')}
 await page.getByRole('button',{name:'Skills',exact:true}).last().click();await page.getByRole('heading',{name:'Einmal erklären. Immer passend antworten.',exact:true}).waitFor();await page.locator('.skill-card').filter({has:page.getByRole('heading',{name:'Texte überarbeiten',exact:true})}).waitFor();await capture('skills');
 const textCard=page.locator('.skill-card').filter({has:page.getByRole('heading',{name:'Texte überarbeiten',exact:true})});await textCard.getByRole('button',{name:'Bearbeiten',exact:true}).click();const skillEditor=page.getByRole('dialog',{name:'Skill bearbeiten',exact:true});await skillEditor.getByRole('radio',{name:/Bei Erwähnung/}).waitFor();await capture('skilleditor');await skillEditor.getByRole('button',{name:'Skill-Editor schließen',exact:true}).click();await skillEditor.waitFor({state:'hidden'});await page.setViewportSize({width:1440,height:980});
 await page.getByRole('button',{name:'Neues Gespräch',exact:true}).first().click();await page.getByLabel('Nachricht',{exact:true}).fill('Ein rein synthetisches Beispiel: Zeige eine kurze Antwort mit Herkunftshinweis.');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await page.getByText('Antwort abgeschlossen',{exact:true}).waitFor();await page.locator('.answer-processing').filter({hasText:'Lokal · synthetic-fixture'}).waitFor();await capture('processing');
 await page.getByRole('button',{name:'Aktionen und Anhänge',exact:true}).click();await page.getByRole('menuitem',{name:/Skill einsetzen/}).click();const chatSkills=page.getByRole('dialog',{name:'Skill im Chat einsetzen',exact:true});await chatSkills.getByRole('button',{name:/Klar und kompakt/}).waitFor();await capture('skillchat');await chatSkills.getByRole('button',{name:'Skillauswahl schließen',exact:true}).click();
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
 // Preserved partial output is an isolated synthetic illustration, never a failed live chat.
 const partialResult=await page.request.post(base+'/api/conversations',{headers:{'X-CSRF-Token':csrf,Origin:base},data:{cloud_allowed:false}});
 if(!partialResult.ok())throw Error('Synthetic partial conversation could not be created');
 const partial=await partialResult.json();
 const partialText='## Projekt Aurora: Eine klare Perspektive\n\n*Synthetische Illustration einer erhaltenen Teilantwort.*\n\n### 1. Den Überblick gewinnen\n\nWir sammeln die wichtigsten Fragen und ordnen die vorhandenen Quellen. Ein gemeinsames Ziel hilft, die Recherche auf die Informationen zu konzentrieren, die eine Entscheidung wirklich unterstützen.\n\n### 2. Ergebnisse nachvollziehbar machen\n\nJede wichtige Aussage soll auf eine Quelle oder eine sichtbar gekennzeichnete Annahme zurückgehen. So lässt sich später prüfen, wie ein Ergebnis zustande gekommen ist.\n\n### 3. Die nächsten Schritte\n\nFür die nächste Projektphase empfehlen wir';
 await page.route('**/api/conversations/'+partial.id,async route=>{if(route.request().method()!=='GET'){await route.continue();return;}await route.fulfill({json:{...partial,title:'Projekt Aurora · Erhaltene Teilantwort',title_status:'succeeded',messages:[{id:'synthetic-partial-user',role:'user',content:'Erstelle eine ausführliche Übersicht zu unserem Beispielprojekt Aurora.',label:'LOCAL_ONLY'},{id:'synthetic-partial-answer',role:'assistant',content:partialText,label:'LOCAL_ONLY',processing:{run_id:'synthetic-partial-run',provider:'local',model:'synthetic-fixture',model_used:true,status:'failed'}}],runs:[{id:'synthetic-partial-run',status:'failed',error:'Die Antwort hat das Zeitlimit erreicht. Die bisher erzeugte Teilantwort bleibt erhalten.',user_message_id:'synthetic-partial-user',assistant_message_id:'synthetic-partial-answer',events:[]}]}});});
 await page.goto(base+'/?view=Chat&chat='+partial.id);
 await page.getByRole('heading',{name:'Projekt Aurora: Eine klare Perspektive',exact:true}).waitFor();
 await page.locator('.answer-partial').filter({hasText:'Teilantwort · unvollständig'}).waitFor();
 await page.locator('.chat-scroll').evaluate(el=>{el.scrollTop=el.scrollHeight;});
 await capture('partial');
 // Capture the failed-run illustration too so all gallery views match the active design.
 const errorResult=await page.request.post(base+'/api/conversations',{headers:{'X-CSRF-Token':csrf,Origin:base},data:{cloud_allowed:false}});
 if(!errorResult.ok())throw Error('Synthetic error conversation could not be created');
 const errorChat=await errorResult.json();
 await page.route('**/api/conversations/'+errorChat.id,async route=>{if(route.request().method()!=='GET'){await route.continue();return}await route.fulfill({json:{...errorChat,title:'Synthetische Recherche',title_status:'succeeded',messages:[{id:'synthetic-error-user',role:'user',content:'Erstelle eine Recherche zum fiktiven Projekt Aurora.',label:'LOCAL_ONLY'}],runs:[{id:'synthetic-error-run',status:'failed',provider:'local',error:'Synthetischer Recherchefehler: keine Webquellen verfügbar.',user_message_id:'synthetic-error-user',events:[]}]}})});
 await page.goto(base+'/?view=Chat&chat='+errorChat.id);await page.getByRole('alert').filter({hasText:'Synthetischer Recherchefehler'}).waitFor();await capture('runerror');
 // Review-only deletion screenshots: isolated synthetic objects, cancel both dialogs.
 const deleteProjectResult=await page.request.post(base+'/api/projects',{headers:{'X-CSRF-Token':csrf,Origin:base},data:{name:'Projekt Atlas · Demo',description:'Ein fiktiver Projektraum für die Illustration der endgültigen Löschung.',instructions:''}});
 if(!deleteProjectResult.ok())throw Error('Synthetic deletion project creation failed');
 const deleteProject=await deleteProjectResult.json();
 const deleteSourceResult=await page.request.post(base+'/api/projects/'+deleteProject.id+'/sources',{headers:{'X-CSRF-Token':csrf,Origin:base,'Content-Type':'application/octet-stream','X-File-Name':'Atlas-Notizen.txt'},data:'Ausschließlich synthetische Notizen zum fiktiven Projekt Atlas.'});
 if(!deleteSourceResult.ok())throw Error('Synthetic deletion source upload failed');
 for(let n=0;n<100;n++){const sources=await(await page.request.get(base+'/api/projects/'+deleteProject.id+'/sources')).json();if(sources[0]?.status==='ready')break;if(n===99)throw Error('Synthetic deletion source did not settle');await page.waitForTimeout(100)}
 const deleteChatResult=await page.request.post(base+'/api/conversations',{headers:{'X-CSRF-Token':csrf,Origin:base},data:{project_id:deleteProject.id}});if(!deleteChatResult.ok())throw Error('Synthetic deletion chat creation failed');const deleteChat=await deleteChatResult.json();await page.request.patch(base+'/api/conversations/'+deleteChat.id,{headers:{'X-CSRF-Token':csrf,Origin:base},data:{title:'Atlas · Fiktive Planung'}});
 const deleteMessageResult=await page.request.post(base+'/api/conversations/'+deleteChat.id+'/messages',{headers:{'X-CSRF-Token':csrf,Origin:base},data:{content:'Fiktive Planung für Projekt Atlas: Wir sammeln Ideen und halten die nächsten Schritte fest.',local_only:true,model_local_only:true,web_search_allowed:false,request_id:crypto.randomUUID()}});if(!deleteMessageResult.ok())throw Error('Synthetic deletion message failed');
 await page.goto(base+'/?view=Projekte&project='+deleteProject.id);await page.getByRole('button',{name:'Projekt löschen',exact:true}).click();const projectDeletion=page.getByRole('dialog',{name:'Projekt endgültig löschen?',exact:true});await projectDeletion.getByRole('button',{name:'Endgültig löschen',exact:true}).waitFor();await page.waitForFunction(()=>![...document.querySelectorAll('.delete-dialog button')].find(b=>b.textContent.includes('Endgültig löschen')).disabled);await capture('deleteproject');await projectDeletion.getByRole('button',{name:'Abbrechen',exact:true}).click();
 await page.goto(base+'/?view=Chat&chat='+deleteChat.id);await page.getByRole('button',{name:'Gespräch löschen',exact:true}).click();const chatDeletion=page.getByRole('dialog',{name:'Gespräch endgültig löschen?',exact:true});await chatDeletion.getByRole('button',{name:'Endgültig löschen',exact:true}).waitFor();await page.waitForFunction(()=>![...document.querySelectorAll('.delete-dialog button')].find(b=>b.textContent.includes('Endgültig löschen')).disabled);await capture('deletechat');await chatDeletion.getByRole('button',{name:'Abbrechen',exact:true}).click();
 if(errors.length)throw Error(errors.join('\n'));
 console.log((JSON.parse(await readFile(new URL('../website/project.json',import.meta.url),'utf8')).screenshots.length)+' gallery screenshots plus mobile captured with synthetic data only.');
}finally{await browser.close();}
