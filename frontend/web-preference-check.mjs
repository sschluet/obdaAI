import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
const base='http://127.0.0.1:18765',browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[];
page.on('pageerror',error=>errors.push(error.message));
let detail;
try{
 await page.goto(base);const auth=await loginFixture(page);
 const response=await page.request.post(base+'/api/conversations',{headers:{'X-CSRF-Token':auth.csrf,Origin:base},data:{cloud_allowed:false}});if(!response.ok())throw Error('Could not create synthetic conversation');
 const conversation=await response.json();detail={...conversation,title:'Synthetic frictionless web',messages:[],runs:[]};
 await page.route('**/api/conversations/'+conversation.id,async route=>{if(route.request().method()==='GET')await route.fulfill({json:detail});else await route.continue()});
 await page.route('**/api/conversations/'+conversation.id+'/**',async route=>{
  const request=route.request();if(!['POST','PATCH'].includes(request.method())||!(/\/(messages(?:\/[^/]+)?|retry)$/.test(new URL(request.url()).pathname))){await route.continue();return}
  const body=request.postDataJSON();requests.push(body);const id='synthetic-run-'+requests.length;
  if(body.content){detail.messages=body.revision?[{id:'synthetic-user',role:'user',content:body.content,label:'LOCAL_ONLY'}]:[...detail.messages,{id:'synthetic-user',role:'user',content:body.content,label:'LOCAL_ONLY'}]}
  detail={...detail,messages:[...detail.messages,{id:'synthetic-answer-'+id,role:'assistant',content:'Synthetic response '+requests.length,label:'LOCAL_ONLY'}],runs:[...detail.runs,{id,status:'succeeded',provider:'local',error:null}]};
  const events=[['run',{id}],['delta',{text:'Synthetic response '+requests.length}],['done',{status:'succeeded'}]];
  await route.fulfill({headers:{'content-type':'text/event-stream'},body:events.map(([event,data])=>`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('')});
 });
 await page.goto(base+'/?view=Chat&chat='+conversation.id);
 const composer=page.locator('form.composer'),enabled=composer.getByRole('button',{name:'Websuche aktiviert',exact:true}),off=composer.getByRole('button',{name:'Websuche',exact:true}),input=composer.getByLabel('Nachricht',{exact:true}),model=composer.getByRole('button',{name:'Modellwahl',exact:true});
 await enabled.click({trial:true});if(await enabled.isDisabled())throw Error('Empty composer blocks web preference');
 const query='  Synthetic public research '+ 'topic '.repeat(100);
 await input.fill(query);await composer.getByRole('button',{name:'Nachricht senden',exact:true}).click();await page.getByText('Antwort abgeschlossen',{exact:true}).waitFor();
 if(requests[0]?.web_query!==query.trim().slice(0,500)||requests[0]?.web_search_allowed!==true||requests[0]?.local_only!==false)throw Error('Send lost web preference/query');
 await enabled.waitFor();await page.getByRole('button',{name:'Antwort erneut erzeugen',exact:true}).click();await page.getByText('Synthetic response 2',{exact:true}).waitFor();
 if(requests[1]?.web_query!==query.trim().slice(0,500)||!requests[1]?.web_search_allowed)throw Error('Retry lost current query/grant');
 await page.getByRole('button',{name:'Nachricht bearbeiten',exact:true}).click();await page.locator('#edited-message').fill('Synthetic edited public research');await page.getByRole('button',{name:'Ändern und neu antworten',exact:true}).click();await page.getByText('Synthetic response 3',{exact:true}).waitFor();
 if(requests[2]?.web_query!=='Synthetic edited public research'||!requests[2]?.web_search_allowed)throw Error('Edit lost edited query/grant');
 await model.click();await page.getByRole('menuitemradio',{name:'Nur lokal',exact:true}).click();if(!await off.isDisabled())throw Error('Local mode exposes web');
 await input.fill('Synthetic local request');await composer.getByRole('button',{name:'Nachricht senden',exact:true}).click();await page.getByText('Synthetic response 4',{exact:true}).waitFor();
 if(requests[3]?.web_search_allowed!==false||requests[3]?.local_only!==true||requests[3]?.web_query!==undefined)throw Error('Local mode sent external query');
 await model.click();await page.getByRole('menuitemradio',{name:'Auto',exact:true}).click();await enabled.waitFor();
 detail={...detail,cloud_allowed:true,cloud_provider:'openrouter'};await page.reload();await enabled.waitFor();
 await model.click();await page.getByRole('menuitemradio',{name:'Auto',exact:true}).click();
 await input.fill('Synthetic local model with web');await composer.getByRole('button',{name:'Nachricht senden',exact:true}).click();await page.getByText('Synthetic response 5',{exact:true}).waitFor();
 if(requests[4]?.model_local_only!==false||requests[4]?.local_only!==false||requests[4]?.web_search_allowed!==true)throw Error('Auto forced local processing or blocked web');
 await enabled.click();await input.fill('Synthetic changed draft');if(!await off.isEnabled())throw Error('Typing resets web preference');await composer.getByRole('button',{name:'Nachricht senden',exact:true}).click();await page.getByText('Synthetic response 6',{exact:true}).waitFor();if(requests[5]?.web_search_allowed!==false||requests[5]?.web_query!==undefined)throw Error('Disabled preference sent a query');await page.reload();await off.waitFor();
 await page.getByRole('button',{name:'Einstellungen',exact:true}).click();const setting=page.getByRole('checkbox',{name:'Webrecherche automatisch erlauben',exact:true});await setting.waitFor();if(await setting.isChecked())throw Error('Disabled preference did not persist');await setting.check();await page.reload();await setting.waitFor();if(!await setting.isChecked())throw Error('Enabled settings preference did not persist');
 await page.locator('button.new').click();await enabled.waitFor();if(!await enabled.isEnabled())throw Error('New conversation resets preference');
 if(await page.getByRole('dialog',{name:'Websuche für diese Nachricht',exact:true}).count())throw Error('Search confirmation remains');
 await page.setViewportSize({width:320,height:640});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Web control overflows on mobile');
 if(errors.length)throw Error(errors.join('; '));console.log('Frictionless web preference passed: enabled by default, direct toggle, send/retry/edit scoped query, local-only override, settings persistence, new chat, mobile. Synthetic UI only.');
}finally{await browser.close()}
