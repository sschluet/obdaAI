import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
const base='http://127.0.0.1:18765',browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on('pageerror',error=>errors.push(error.message));
const failure='Synthetische Zeitgrenze: Teilantwort bleibt erhalten.',liveFailure='Synthetischer allgemeiner Providerfehler';
const partial=id=>({id:'partial-'+id,role:'assistant',content:'Synthetische lange Teilantwort mit erhaltenem Inhalt.',label:'LOCAL_ONLY',processing:{run_id:id,provider:'local',model:'synthetic-fixture',model_used:true,status:'failed'}});
let state='failed',attempt=0,detail;
const run=(id,status,error)=>({id,status,provider:'local',model:'synthetic-fixture',answer_model_used:status==='succeeded',reason:'synthetic UI check',error});
try{
 await page.goto(base);const auth=await loginFixture(page);
 const created=await page.request.post(base+'/api/conversations',{headers:{'X-CSRF-Token':auth.csrf,'Origin':base},data:{cloud_allowed:false}});if(!created.ok())throw Error('Fixture conversation creation failed: '+created.status()+' '+await created.text());
 const conversation=await created.json();
 detail={...conversation,title:'Synthetische Fehlerprüfung',messages:[{id:'synthetic-user',role:'user',content:'Synthetische Recherche',label:'LOCAL_ONLY'},partial('failure-1')],runs:[run('failure-1','failed',failure)]};
 await page.route('**/api/conversations/'+conversation.id,async route=>{if(route.request().method()!=='GET'){await route.continue();return}await route.fulfill({json:detail});});
 await page.route('**/api/conversations/'+conversation.id+'/retry',async route=>{
  attempt++;
  if(state==='http-error'){await route.fulfill({status:503,json:{detail:'Synthetischer Transportfehler'}});return}
  const id='retry-'+attempt,events=[['run',{id}],['provider',{name:'local',reason:'synthetic UI check',model:'synthetic-fixture',model_used:state==='succeeded'}]];
  if(state==='failed'){detail={...detail,messages:[...detail.messages.filter(m=>m.role==='user'),partial(id)],runs:[...detail.runs,run(id,'failed',failure)]};events.push(['delta',{text:partial(id).content}],['error',{message:liveFailure}],['done',{status:'failed'}]);}
  else{detail={...detail,runs:[...detail.runs,run(id,'succeeded',null)],messages:[...detail.messages.filter(m=>m.role==='user'),{id:'synthetic-answer',role:'assistant',content:'Synthetische erfolgreiche Antwort.',label:'LOCAL_ONLY',processing:{run_id:id,provider:'local',model:'synthetic-fixture',model_used:true,status:'succeeded'}}]};events.push(['delta',{text:'Synthetische erfolgreiche Antwort.'}],['done',{status:'succeeded'}]);}
  await new Promise(resolve=>setTimeout(resolve,350));
  await route.fulfill({headers:{'content-type':'text/event-stream'},body:events.map(([event,data])=>`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('')});
 });
 await page.goto(base+'/?view=Chat&chat='+conversation.id);
 const alerts=page.getByRole('alert'),retry=page.getByRole('button',{name:'Antwort erneut erzeugen',exact:true});
 await alerts.filter({hasText:failure}).waitFor();if(await alerts.count()!==1||await page.locator('.error').count()!==1)throw Error('Persisted failure is duplicated or inaccessible');
 await page.locator('.answer-processing').filter({hasText:'Teilantwort · unvollständig'}).waitFor();
 await retry.click();await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).waitFor();if(await alerts.count())throw Error('Previous failure remains visible during retry');
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).waitFor();if(await alerts.count()!==1||await page.locator('.error').count()!==1)throw Error('SSE and persisted failure are shown twice');
 if(await alerts.first().textContent()!==failure)throw Error('Generic SSE error masks the precise persisted failure');
 await page.getByText(partial('fixture').content,{exact:true}).waitFor();await page.locator('.answer-processing').filter({hasText:'Lokal · synthetic-fixture · Teilantwort · unvollständig'}).waitFor();
 if(process.env.HUB_ERROR_SCREENSHOT)await page.screenshot({path:process.env.HUB_ERROR_SCREENSHOT,fullPage:false});
 await page.reload();await alerts.filter({hasText:failure}).waitFor();if(await alerts.count()!==1)throw Error('Reload lost or duplicated run failure');await page.locator('.answer-processing').filter({hasText:'Teilantwort · unvollständig'}).waitFor();
 state='http-error';await retry.click();await alerts.filter({hasText:'Synthetischer Transportfehler'}).waitFor();if(await alerts.count()!==1)throw Error('Unrelated error was hidden or duplicated');
 state='succeeded';await retry.click();await page.getByText('Synthetische erfolgreiche Antwort.',{exact:true}).waitFor();await page.getByRole('button',{name:'Nachricht senden',exact:true}).waitFor();if(await alerts.count())throw Error('Successful retry retains old error');
 await page.locator('.answer-processing').filter({hasText:'Lokal · synthetic-fixture'}).waitFor();
 await page.reload();await page.locator('.answer-processing').filter({hasText:'Lokal · synthetic-fixture'}).waitFor();if(await alerts.count())throw Error('Reload restores obsolete error after success');
 state='http-error';await retry.click();await alerts.filter({hasText:'Synthetischer Transportfehler'}).waitFor();await page.locator('button.new').click();await page.getByRole('heading',{name:'Womit möchtest du beginnen?'}).waitFor();if(await alerts.count())throw Error('New conversation retains prior failure');
 await page.setViewportSize({width:390,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Error UI causes mobile overflow');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Run error UI passed: one accessible authoritative persisted/SSE failure, partial content and model attribution visibly retained after failure/reload, retry hides previous failure, unrelated HTTP errors preserved, successful retry/reload clears failure, attribution preserved, new conversation clears stale errors. Synthetic response rendering only.');
}finally{await browser.close()}
