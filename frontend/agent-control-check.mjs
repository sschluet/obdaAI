import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
const base=process.env.HUB_AGENT_ORIGIN||'http://127.0.0.1:18769';
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1100}});
page.setDefaultTimeout(20000);
const errors=[];page.on('pageerror',e=>errors.push(e.message));
let headers,profile,chat;
async function call(path,method='GET',data){const r=await page.request.fetch(base+'/api'+path,{method,headers,data});if(!r.ok())throw Error(method+' '+path+' '+r.status()+' '+await r.text());return r.json()}
try{
 await page.goto(base);const session=await loginFixture(page);headers={'Origin':base,'X-CSRF-Token':session.csrf};
 profile=await call('/integrations','POST',{name:'Paperless Aurora',kind:'paperless',url:'https://agent.example.test',auth:'api_key',secret:'synthetic-agent-token'});
 profile=await call('/integrations/'+profile.id+'/control','PATCH',{expected_revision:profile.revision,enabled:true});
 let current=(await call('/integrations')).integrations.find(p=>p.id===profile.id);
 const write=await call('/integrations/'+profile.id+'/write-control','PATCH',{expected_revision:current.revision,writes_enabled:true});
 let policy=await call('/integrations/'+profile.id+'/agent-policy');
 policy=await call('/integrations/'+profile.id+'/agent-policy','PUT',{expected_revision:policy.revision,expected_profile_revision:write.revision,rules:{...policy.rules,enabled:true,autonomous:false,http_prefixes:['/api/'],http_methods:['GET','PATCH']}});
 const pause=await call('/action-policy');if(pause.paused)await call('/action-policy','PATCH',{expected_revision:pause.revision,paused:false});
 chat=await call('/conversations','POST',{});
 await call('/integration-bindings/conversation/'+chat.id,'PUT',{expected_revision:0,selection_mode:'manual',integration_ids:[profile.id]});
 await page.goto(base+'/?chat='+chat.id);await page.getByLabel('Systeme steuern',{exact:true}).check();
 const composer=page.locator('.composer textarea');
 await composer.fill('Ändere das synthetische Dokument. Frage zuerst nach dem gewünschten Titel.');
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
 await page.getByText('Welchen Titel soll das synthetische Dokument erhalten?',{exact:true}).first().waitFor();
 await composer.fill('Agentenabnahme');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
 const panel=page.getByRole('region',{name:'Systemsteuerung',exact:true});
 const approve=panel.getByRole('button',{name:'Diesen Schritt freigeben und fortsetzen',exact:true});await approve.waitFor();
 let jobs=await call('/agent-runs?conversation_id='+chat.id);let job=await call('/agent-runs/'+jobs[0].id);
 if(job.status!=='awaiting_approval'||job.steps.some(s=>s.kind==='effect'&&s.status==='succeeded'))throw Error('Effect before exact approval');
 await approve.click();await panel.getByText(/Ausführung und Prüfschritte abgeschlossen/).first().waitFor();
 job=await call('/agent-runs/'+job.id);
 if(job.status!=='succeeded'||!job.steps.find(s=>s.kind==='effect')?.result.effect_verified)throw Error('Missing independent verification');
 if(process.env.HUB_AGENT_CAPTURE){await panel.getByText(/Ausführung und Prüfschritte abgeschlossen/).first().click();await page.screenshot({path:process.env.HUB_AGENT_CAPTURE,fullPage:true})}
 await page.reload();await page.getByRole('region',{name:'Systemsteuerung',exact:true}).getByText(/Ausführung und Prüfschritte abgeschlossen/).first().waitFor();
 policy=await call('/integrations/'+profile.id+'/agent-policy');
 await call('/integrations/'+profile.id+'/agent-policy','PUT',{expected_revision:policy.revision,expected_profile_revision:policy.profile_revision,rules:{...policy.rules,autonomous:true}});

 await page.getByRole('button',{name:'Aufgaben',exact:true}).click();
 await page.getByRole('button',{name:'Neue Aufgabe',exact:true}).click();
 const editor=page.getByRole('dialog',{name:'Aufgabe bearbeiten',exact:true});
 await editor.getByLabel('Name der Aufgabe',{exact:true}).fill('Agentenaufgabe Aurora');
 await editor.getByLabel('Was soll erledigt werden?',{exact:true}).fill('Benenne das synthetische Dokument um und prüfe den gespeicherten Titel.');
 await editor.locator('summary').filter({hasText:'Weitere Einstellungen'}).click();
 await editor.getByLabel('Art der Aufgabe',{exact:true}).selectOption('agent.run');
 if(await editor.getByLabel('Autonomieprofil',{exact:true}).isVisible())throw Error('Obsolete fixed autonomy exposed for agent task');
 await editor.getByLabel('Agentenautonomie',{exact:true}).selectOption('bounded_autonomous');
 await editor.getByRole('button',{name:'Aufgabe anlegen',exact:true}).click();
 await page.getByRole('heading',{name:'Agentenaufgabe Aurora',exact:true,level:2}).waitFor();
 await page.getByText(/Modell: lokales Modell, siehe Laufbeleg/).waitFor();
 let task=(await call('/tasks')).find(t=>t.spec.title==='Agentenaufgabe Aurora');
 if(task.spec.steps[0].tool_id!=='agent.run'||task.spec.autonomy!=='bounded_autonomous')throw Error('Shared agent task not saved');
 await call('/integration-bindings/task/'+task.id,'PUT',{expected_revision:0,selection_mode:'manual',integration_ids:[profile.id]});
 task=await call('/tasks/'+task.id+'/control','PATCH',{expected_revision:task.revision,expected_control_revision:task.control_revision,paused:false});
 await call('/tasks/'+task.id+'/runs','POST',{request_id:crypto.randomUUID(),expected_revision:task.revision,expected_control_revision:task.control_revision,spec_sha256:task.spec_sha256});
 await page.getByRole('region',{name:'Systemsteuerung',exact:true}).getByText(/Ausführung und Prüfschritte abgeschlossen/).first().waitFor();
 const taskJobs=await call('/agent-runs?task_id='+task.id);
 if(taskJobs[0]?.status!=='succeeded')throw Error('Task did not use the verified shared loop');
 await page.getByRole('button',{name:'Chat',exact:true}).click();await page.goto(base+'/?chat='+chat.id);
 await page.getByLabel('Systeme steuern',{exact:true}).check();await composer.fill('Synthetischer Abnahmetest mit Antwortverlust.');await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
 await panel.getByText(/Wirkung unklar/).first().waitFor();
 jobs=await call('/agent-runs?conversation_id='+chat.id);job=await call('/agent-runs/'+jobs[0].id);
 if(job.status!=='uncertain'||job.steps.filter(s=>s.kind==='effect').length!==1)throw Error('Uncertain effect retried');
 await page.setViewportSize({width:320,height:740});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Agent chat mobile overflow');
 if(errors.length)throw Error(errors.join('; '));
 console.log('Agent chat UI passed: same-chat clarification, dynamic read/write, exact approval, independent verification, reload, autonomous rules, shared task creation/execution, lost-response no retry and 320px.');
}catch(e){await page.screenshot({path:'.local/agent-ui-failure.png',fullPage:true});console.error((await page.locator('body').innerText()).slice(-6000));throw e}
finally{if(headers&&chat){try{const jobs=await call('/agent-runs?conversation_id='+chat.id);for(const job of jobs)if(['queued','running','awaiting_approval','awaiting_input'].includes(job.status))await call('/agent-runs/'+job.id+'/cancel','POST',{});const p=await call('/conversations/'+chat.id+'/deletion');if(!p.blockers.length)await call('/conversations/'+chat.id,'DELETE',{expected_state:p.expected_state})}catch(e){errors.push(e.message)}}if(headers&&profile){try{const p=(await call('/integrations')).integrations.find(p=>p.id===profile.id);if(p)await call('/integrations/'+p.id,'DELETE',{expected_revision:p.revision})}catch(e){errors.push(e.message)}}await browser.close()}
