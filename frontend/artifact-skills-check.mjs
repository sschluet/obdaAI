// Synthetic package masters exercise real binding/rendering; preview pixels are fixture-only.
import {chromium} from 'playwright';
import {execFileSync} from 'node:child_process';
import {loginFixture} from './fixture-login.mjs';
const base=process.env.ARTIFACT_FIXTURE_ORIGIN||'http://127.0.0.1:18765';
if(!['http://127.0.0.1:18765','http://127.0.0.1:18767'].includes(base))throw Error('Synthetic fixture only');
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});let csrf;const skills=[];let project;
async function api(path,method='GET',data){const r=await page.request.fetch(base+'/api'+path,{method,headers:{Origin:base,'X-CSRF-Token':csrf},...(data===undefined?{}:{data})});if(!r.ok())throw Error(path+' '+r.status()+' '+await r.text());return r.json()}
function packageData(name,kind){return execFileSync(process.env.HUB_TEST_PYTHON||'../.venv/bin/python',['-c',`import io,sys,zipfile
from docx import Document
from pptx import Presentation
name,kind=sys.argv[1:]
master=io.BytesIO()
if kind=='docx':
 d=Document();d.sections[0].header.paragraphs[0].text='SYNTHETIC MASTER HEADER';d.add_paragraph('Replace this sample body');d.save(master)
elif kind=='pptx':
 d=Presentation();d.slide_width=9144000;d.save(master)
out=io.BytesIO()
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
 z.writestr('SKILL.md','---\\nname: '+name+'\\ndescription: Synthetic template instructions\\n---\\nUse the supplied master for the requested file.')
 if kind in ('docx','pptx'):z.writestr('templates/master.'+kind,master.getvalue())
sys.stdout.buffer.write(out.getvalue())`,name,kind])}
async function install(name,kind){const bytes=packageData(name,kind);const r=await page.request.post(base+'/api/skills/import-package',{headers:{Origin:base,'X-CSRF-Token':csrf,'X-File-Name':'synthetic.skill','Content-Type':'application/octet-stream'},data:bytes});if(!r.ok())throw Error('Synthetic package '+r.status()+' '+await r.text());let s=await r.json();skills.push(s.id);s=await api('/skills/'+s.id+'/trust','POST',{expected_revision:s.revision,sha256:s.sha256,enabled:true});return s}
try{
 await page.goto(base);csrf=(await loginFixture(page)).csrf;
 const doc=await install('Synthetic document master','docx');await install('avendis-praesentation','pptx');const modern=await install('avendis-praesentation-modern','style');
 project=await api('/projects','POST',{name:'Synthetic template binding '+Date.now()});
 await page.goto(base+'/?view=Projekte&project='+project.id+'&projectTab=files');await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).waitFor();
 for(const [kind,chosen] of [['docx',doc],['pptx',modern],['xlsx',null]]){
  await page.getByRole('button',{name:'Neue Datei erstellen',exact:true}).click();const dialog=page.getByRole('dialog',{name:'Datei erstellen',exact:true});await dialog.getByRole('radio',{name:({docx:'Word-Dokument',pptx:'PowerPoint-Präsentation',xlsx:'Excel-Tabelle'})[kind],exact:true}).check();
  if(chosen)await dialog.getByRole('checkbox',{name:'Datei-Skill '+chosen.name,exact:true}).check();
  await dialog.getByLabel('Gewünschtes Ergebnis',{exact:true}).fill('Create a synthetic '+kind+' file with short verifiable example content.');await dialog.getByRole('button',{name:'Lokal entwerfen',exact:true}).click();await dialog.getByText(/Lokaler Entwurf bereit/).waitFor();
  if(chosen)await dialog.getByText(/Gebundene Originalvorlage:/).waitFor();
  await dialog.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();await dialog.waitFor({state:'hidden'});const list=await api('/projects/'+project.id+'/artifacts');const row=list.find(r=>r.kind===kind);if(!row)throw Error('Missing generated '+kind);if(chosen&&(!row.spec.template||!row.draft.skills.some(s=>s.id===chosen.id)))throw Error('Selected master or receipt dropped');if(kind==='pptx'&&row.spec.template.style!=='modern')throw Error('Optional modern style not bound');if(kind==='xlsx'&&!row.spec.plan.sheets.length)throw Error('Spreadsheet content dropped');
  await page.locator('.citation').filter({hasText:row.title}).getByRole('button',{name:'Vorschau öffnen',exact:true}).click();const preview=page.getByRole('dialog',{name:'Dateivorschau',exact:true});await preview.getByLabel('Ich habe alle Vorschauseiten geprüft.',{exact:true}).check();await preview.getByRole('button',{name:'Diese Dateiversion freigeben',exact:true}).click();await preview.waitFor({state:'hidden'});
  if(kind==='docx'){const download=await page.request.get(base+'/api/projects/'+project.id+'/artifacts/'+row.artifact_id+'/versions/'+row.revision+'/download');if(!download.ok())throw Error('Word download missing');const inspected=execFileSync(process.env.HUB_TEST_PYTHON||'../.venv/bin/python',['-c',`import io,sys,zipfile
with zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())) as z:
 assert b'SYNTHETIC MASTER HEADER' in z.read('word/header1.xml')
`],{input:await download.body()});if(inspected.length)throw Error('Unexpected native output');
   await page.locator('.citation').filter({hasText:row.title}).getByRole('button',{name:'Neue Version bearbeiten',exact:true}).click();const edit=page.getByRole('dialog',{name:'Datei erstellen',exact:true});await edit.getByRole('button',{name:'Datei und Vorschau erstellen',exact:true}).click();await edit.waitFor({state:'hidden'});const versions=await api('/projects/'+project.id+'/artifacts');const next=versions.find(r=>r.artifact_id===row.artifact_id&&r.revision===2);if(next?.spec.template?.asset_sha256!==row.spec.template.asset_sha256)throw Error('Manual revision lost original template');
  }
 }
 console.log('Synthetic artifact skills UX passed: active master choice, exact revision receipts, real Word header preservation, manual revision retains master, optional modern presentation with base dependency, Excel sheet content, review.');
}finally{for(const id of skills){const list=await api('/skills');const s=list.find(s=>s.id===id);if(s)await api('/skills/'+id,'DELETE',{expected_revision:s.revision,sha256:s.sha256})}await browser.close()}
