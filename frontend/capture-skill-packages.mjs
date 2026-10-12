// Public screenshots use a generated example master, never user packages.
import {chromium} from 'playwright';import {execFileSync} from 'node:child_process';import {loginFixture} from './fixture-login.mjs';
const base=process.env.SKILLS_FIXTURE_ORIGIN||'http://127.0.0.1:18765';if(!['http://127.0.0.1:18765','http://127.0.0.1:18767'].includes(base))throw Error('Synthetic fixture only');
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:1040}});let csrf;const owned=[];
async function api(path,method='GET',data){const r=await page.request.fetch(base+'/api'+path,{method,headers:{Origin:base,'X-CSRF-Token':csrf},...(data===undefined?{}:{data})});if(!r.ok())throw Error(path+' '+r.status());return r.json()}
try{await page.goto(base);csrf=(await loginFixture(page)).csrf;
const buffer=execFileSync(process.env.HUB_TEST_PYTHON||'../.venv/bin/python',['-c',`import io,sys,zipfile
from docx import Document
master=io.BytesIO();d=Document();d.sections[0].header.paragraphs[0].text='BEISPIELVORLAGE';d.add_heading('Bericht',0);d.add_paragraph('Demo-Struktur für einen Bericht.');d.save(master)
out=io.BytesIO()
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
 z.writestr('bericht/SKILL.md','---\\nname: Bericht mit Dokumentvorlage\\ndescription: Erstellt strukturierte Berichte mit einem eigenen Word-Master.\\n---\\nVerwende die Dokumentvorlage für Berichte. Nenne zuerst das Ziel. Trenne belegte Fakten und offene Fragen. Nutze diesen Skill nur für einen angeforderten Bericht.')
 z.writestr('bericht/templates/bericht.docx',master.getvalue())
 z.writestr('bericht/references/aufbau.md','# Berichtstruktur\\nZiel, Erkenntnisse, offene Fragen, nächste Schritte.')
 z.writestr('bericht/scripts/pruefung.py','# Archiviertes Beispiel. Nicht ausgeführt.')
sys.stdout.buffer.write(out.getvalue())`]);
const r=await page.request.post(base+'/api/skills/import-package',{headers:{Origin:base,'X-CSRF-Token':csrf,'X-File-Name':'beispiel.skill','Content-Type':'application/octet-stream'},data:buffer});if(!r.ok())throw Error('Example import');const skill=await r.json();owned.push(skill.id);await api('/skills/'+skill.id+'/trust','POST',{expected_revision:skill.revision,sha256:skill.sha256,enabled:true});
for(const [name,description,body]of [['Präsentation strukturieren','Bringt eine Idee in klare Folien mit einem roten Faden.','Nutze klare Stichpunkte für angeforderte Präsentationen.'],['Texte überarbeiten','Verbessert Aufbau, Lesbarkeit und Ton beim Aufruf.','Bewahre die Aussage. Verbessere Lesbarkeit, Aufbau und Ton.']]){const s=await api('/skills','POST',{document:'---\n'+JSON.stringify({format:'obdaai-skill-1',name,description,usage:'mention',cloud_allowed:false})+'\n---\n'+body,activate:true});owned.push(s.id)}
await page.getByRole('button',{name:'Skills',exact:true}).click();const card=page.locator('.skill-card').filter({has:page.getByRole('heading',{name:skill.name,exact:true})});await card.waitFor();await page.screenshot({path:'../website/assets/skills.png',animations:'disabled'});await card.getByRole('button',{name:'Bearbeiten',exact:true}).click();const editor=page.getByRole('dialog',{name:'Skill bearbeiten',exact:true});await editor.getByRole('heading',{name:'Vorlagen & Ressourcen',exact:true}).waitFor();await page.screenshot({path:'../website/assets/skilleditor.png',animations:'disabled'});await page.setViewportSize({width:390,height:844});if(await editor.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Mobile package overflow');console.log('Synthetic skill library/package screenshots captured; generated master only.');
}finally{for(const id of owned){const s=(await api('/skills')).find(s=>s.id===id);if(s)await api('/skills/'+id,'DELETE',{expected_revision:s.revision,sha256:s.sha256})}await browser.close()}
