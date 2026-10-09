import {loginFixture} from './fixture-login.mjs';
// Synthetic local browser acceptance, separate from real model-quality checks.
import {chromium} from 'playwright';
import {mkdir} from 'node:fs/promises';
const base='http://127.0.0.1:18765';
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));
let original,csrf;
const api=async(path,method='GET',body)=>{const r=await page.request.fetch(base+'/api'+path,{method,headers:{Origin:base,...(csrf?{'X-CSRF-Token':csrf}:{}),'Content-Type':'application/json'},...(body===undefined?{}:{data:body})});return {status:r.status(),body:await r.json()}};
async function login(target){await target.goto(base);return (await loginFixture(target)).csrf}
async function globalSettings(target){await target.getByRole('button',{name:'Einstellungen',exact:true}).click();await target.getByRole('button',{name:'Antwortverhalten',exact:true}).click();const region=target.getByRole('region',{name:'Antwortvorgaben',exact:true});await region.getByRole('radiogroup',{name:'Antwortsprache',exact:true}).waitFor();return region}
async function save(region){await region.getByRole('button',{name:'Vorgaben speichern',exact:true}).click();await region.getByRole('status').filter({hasText:'Gespeichert.'}).waitFor()}
try{
 csrf=await login(page);original=(await api('/preferences/global')).body;
 let global=await globalSettings(page);
 if(await global.locator('select').count())throw Error('Response preferences still use native dropdowns');
 const language=global.getByRole('radiogroup',{name:'Antwortsprache',exact:true});
 await language.getByRole('radio',{name:'Deutsch',exact:true}).check();
 await language.getByRole('radio',{name:'Deutsch',exact:true}).focus();await page.keyboard.press('ArrowRight');
 if(!await language.getByRole('radio',{name:'Englisch',exact:true}).isChecked())throw Error('Radio keyboard navigation failed');
 await page.keyboard.press('ArrowLeft');
 if(!await language.getByRole('radio',{name:'Deutsch',exact:true}).isChecked())throw Error('Radio keyboard navigation did not restore choice');
 await language.getByRole('radio',{name:'Übernehmen',exact:true}).check();
 if(!await language.getByRole('radio',{name:'Übernehmen',exact:true}).isChecked())throw Error('Per-field inheritance choice failed');
 await global.getByRole('radiogroup',{name:'Antwortsprache',exact:true}).getByRole('radio',{name:'Deutsch',exact:true}).check();
 await global.getByRole('radiogroup',{name:'Antwortlänge',exact:true}).getByRole('radio',{name:'Kurz',exact:true}).check();await save(global);
 await page.reload();global=await globalSettings(page);
 if(!await global.getByRole('radiogroup',{name:'Antwortsprache',exact:true}).getByRole('radio',{name:'Deutsch',exact:true}).isChecked()||!await global.getByRole('radiogroup',{name:'Antwortlänge',exact:true}).getByRole('radio',{name:'Kurz',exact:true}).isChecked())throw Error('Global preferences lost on reload');
 const secondContext=await browser.newContext();try{const second=await secondContext.newPage();await login(second);const shared=await globalSettings(second);if(!await shared.getByRole('radiogroup',{name:'Antwortsprache',exact:true}).getByRole('radio',{name:'Deutsch',exact:true}).isChecked())throw Error('Not shared across browsers')}finally{await secondContext.close()}
 const invalid=await api('/preferences/global','PUT',{expected_revision:(await api('/preferences/global')).body.revision,overrides:{cloud_allowed:true}});if(invalid.status!==422)throw Error('Accepted cloud permission');
 await page.getByRole('button',{name:'Projekte',exact:true}).click();await page.getByRole('button',{name:'Neues Projekt',exact:true}).click();
 const name='Synthetic response preferences '+Date.now();await page.getByLabel('Projektname',{exact:true}).fill(name);await page.getByRole('button',{name:'Projektraum erstellen',exact:true}).click();await page.getByRole('tab',{name:'Vorgaben',exact:true}).click();
 const project=page.getByRole('region',{name:'Antwortvorgaben',exact:true});await project.getByRole('radiogroup',{name:'Ton',exact:true}).getByRole('radio',{name:'Professionell',exact:true}).check();await save(project);
 await project.getByText('Gespeichert wirksam: Deutsch · Persönliche Vorgaben',{exact:false}).waitFor();await project.getByText('Gespeichert wirksam: Professionell · Projekt',{exact:false}).waitFor();
 await page.getByRole('tab',{name:/Gespräche ·/}).click();await page.getByRole('button',{name:'Neues Projektgespräch',exact:true}).click();await page.getByRole('button',{name:'Antwortvorgaben öffnen',exact:true}).click();
 const workbench=page.getByRole('complementary',{name:'Arbeitsbereich neben dem Chat',exact:true});const chat=workbench.getByRole('region',{name:'Antwortvorgaben',exact:true});
 await chat.getByRole('radiogroup',{name:'Antwortlänge',exact:true}).getByRole('radio',{name:'Ausführlich',exact:true}).check();await save(chat);await chat.getByText('Gespeichert wirksam: Ausführlich · Gespräch',{exact:false}).waitFor();await chat.getByText('Gespeichert wirksam: Professionell · Projekt',{exact:false}).waitFor();
 const message='Synthetic preferences verification '+Date.now();await page.getByLabel('Nachricht',{exact:true}).fill(message);await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();await page.getByText('Antwort abgeschlossen',{exact:true}).waitFor();await page.getByText('SYNTHETIC_SOURCE_REPLY:',{exact:false}).waitFor();
 const conversations=(await api('/conversations')).body;let conversation;for(const item of conversations){const full=(await api('/conversations/'+item.id)).body;if(full.messages?.some(m=>m.content===message)){conversation=full;break}}
 if(!conversation||conversation.cloud_allowed)throw Error('Missing chat or granted cloud consent');
 const run=(await api('/runs/'+conversation.runs.at(-1).id)).body;const frozen=run.context.response_preferences;
 if(frozen.effective.length!=='detailed'||frozen.effective.tone!=='professional'||frozen.effective.language!=='de')throw Error('Actual run snapshot style wrong');if(run.provider!=='local')throw Error('Changed provider boundary');
 await chat.getByRole('button',{name:'Alle Vorgaben übernehmen',exact:true}).click();await chat.getByText('Gespeichert wirksam: Kurz · Persönliche Vorgaben',{exact:false}).waitFor();
 const after=(await api('/preferences/conversations/'+conversation.id)).body;if(Object.keys(after.overrides).length||after.origins.length.scope!=='global')throw Error('Reset failed');if((await api('/runs/'+conversation.runs.at(-1).id)).body.context.response_preferences.effective.length!=='detailed')throw Error('Reset mutated finished run');
 await mkdir('../.local/browser',{recursive:true});await page.screenshot({path:'../.local/browser/workspace-preferences.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');await chat.getByRole('radiogroup',{name:'Gliederung',exact:true}).getByRole('radio',{name:'Aufzählungen bevorzugen',exact:true}).check();await save(chat);
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Preference UX passed: global persistence across reload/second browser, project/chat provenance, reset and frozen actual synthetic stream audit, invalid permission rejected, local provider unchanged, mobile save. Synthetic only.');
}finally{if(original&&csrf){const current=(await api('/preferences/global')).body;await api('/preferences/global','PUT',{expected_revision:current.revision,overrides:original.overrides})}await browser.close()}
