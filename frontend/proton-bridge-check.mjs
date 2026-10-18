// UI contract fixture: synthetic Bridge credentials only; never contacts Proton or IMAP.
export async function checkProtonBridgeSetup({page, base, call}) {
 const profile=await call('/integrations','POST',{name:'Proton Mail Aurora',kind:'mcp',url:'https://mail.example.test/mcp',auth:'none',protocol:'2026-07-28'});
 const endpoint=base+'/api/integrations/proton-bridge-setup';
 const registry=base+'/api/integrations';
 const initial={available:true,integration_id:profile.id,name:'Proton Mail Aurora',username:'',revision:profile.revision,connected:false,message:'Bridge ist lokal vorbereitet.',enable_reads:true};
 let state={...initial}, posts=[], getCount=0, enabled=false, checkedRevision=0;
 const controlEndpoint=base+'/api/integrations/'+profile.id+'/control';
 const setupRoute=async route=>{
  if(route.request().method()==='POST'){
   const data=route.request().postDataJSON();posts.push(data);
   if(data.expected_revision!==state.revision||!/^\w{8}-\w{4}-4\w{3}-[89ab]\w{3}-\w{12}$/.test(data.request_id))throw Error('Proton setup revision or request identity missing');
   if(posts.some((p,i)=>i<posts.length-1&&p.request_id===data.request_id))throw Error('Proton setup replayed a request identity');
   enabled=posts.length!==3&&data.enable_reads;
   state={...state,name:data.name,username:data.username,revision:state.revision+1,connected:enabled,message:posts.length===3?'Zugang erneut prüfen.':'Postfach erfolgreich geprüft.',enable_reads:enabled};
   checkedRevision=state.revision;
   if(posts.length===3){await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Synthetische Verbindungsprüfung fehlgeschlagen.'})});return}
  }else getCount++;
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(state)});
 };
 const registryRoute=async route=>{
  if(route.request().method()!=='GET'){await route.continue();return}
  const response=await route.fetch(), data=await response.json();
  data.integrations=data.integrations.map(row=>row.id===profile.id?{...row,name:state.name,revision:state.revision,enabled,check_available:enabled,last_check:{revision:checkedRevision,created:1700000000,status:'succeeded'}}:row);
  await route.fulfill({response,json:data});
 };
 const controlRoute=async route=>{
  if(route.request().method()!=='PATCH')throw Error('Unexpected Proton control method');
  const data=route.request().postDataJSON();
  if(data.expected_revision!==state.revision)throw Error('Proton activation used stale profile revision');
  enabled=data.enabled;state={...state,revision:state.revision+1,connected:false,enable_reads:false};
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id:profile.id,revision:state.revision,enabled})});
 };
 await page.route(endpoint,setupRoute);await page.route(registry,registryRoute);await page.route(controlEndpoint,controlRoute);
 try{
  await page.goto(base+'/?view=Einstellungen&settingsTab=Integrationen');
  const wizard=page.getByRole('dialog',{name:'Proton Mail einrichten',exact:true});
  const row=page.locator('.registry-table tr').filter({hasText:'Proton Mail Aurora'});
  const name=wizard.getByLabel('Name der Verbindung',{exact:true}), username=wizard.getByLabel('Bridge-Benutzername',{exact:true}), password=wizard.getByLabel('Bridge-Passwort',{exact:true});
  const reads=wizard.getByLabel('Lokales Lesen und Suchen über Chat, Aufgaben und Projekte erlauben',{exact:true});
  const submit=wizard.getByRole('button',{name:'Verbindung prüfen und speichern',exact:true});
  const more=async()=>{const details=row.locator('details.registry-more');if(!await details.evaluate(el=>el.open))await details.locator('summary').click()};
  const openRow=async()=>{await row.getByRole('button',{name:/^(Einrichten|Postfach verwalten)$/}).click();await name.waitFor()};
  const review=async()=>{await wizard.getByRole('button',{name:'Weiter zur Prüfung',exact:true}).click();await wizard.getByRole('heading',{name:'3. Prüfen und verbinden',exact:true}).waitFor()};
  const success=async()=>{await submit.click();await wizard.getByText('Postfachverbindung gespeichert und geprüft.',{exact:true}).waitFor();if(await wizard.locator('input[type=password]').count())throw Error('Completed wizard retained a password input');await wizard.getByRole('button',{name:'Fertig',exact:true}).click();await wizard.waitFor({state:'hidden'})};
  await row.waitFor();
  if(await wizard.count()||await page.getByRole('region',{name:'Proton Mail verbinden',exact:true}).count())throw Error('Proton setup appears inline or opens automatically');
  if(posts.length)throw Error('Registry automatically submitted Proton credentials');
  await page.getByRole('button',{name:'Verbindung hinzufügen',exact:true}).click();
  const picker=page.getByRole('dialog',{name:'Neue Verbindung',exact:true});
  await picker.getByRole('button',{name:/^Proton Mail/}).click();
  await wizard.getByRole('heading',{name:'1. Vorbereiten',exact:true}).waitFor();
  if(posts.length||await wizard.locator('input').count())throw Error('Preparation step requests credentials or performs setup');
  await wizard.getByRole('button',{name:'Ich habe die Bridge-Zugangsdaten',exact:true}).click();
  await name.waitFor();
  if(await password.getAttribute('type')!=='password'||await password.inputValue()!==''||await wizard.locator('input').count()!==4)throw Error('Proton wizard exposes credentials or account/2FA login fields');
  await name.fill('Proton Mail Aurora');await username.fill('aurora@example.test');await password.fill('synthetic-bridge-password');await reads.uncheck();
  await review();
  if(posts.length||(await wizard.innerText()).includes('synthetic-bridge-password'))throw Error('Review disclosed password or contacted Bridge before explicit submit');
  await wizard.getByRole('button',{name:'Zurück',exact:true}).click();
  if(await password.inputValue()!=='synthetic-bridge-password'||await reads.isChecked())throw Error('Back navigation lost pending credential/read choice');
  await review();await success();
  if(posts.length!==1||posts[0].password!=='synthetic-bridge-password'||posts[0].enable_reads!==false)throw Error('Initial wizard credential/read choice failed');
  await openRow();
  if(await password.inputValue()!==''||await reads.isChecked())throw Error('Reopened wizard leaked password or widened read choice');
  await reads.check();await review();await success();
  if(posts.length!==2||posts[1].password!==null||posts[1].enable_reads!==true||posts[1].expected_revision!==profile.revision+1)throw Error('Wizard did not preserve stored Bridge password on blank update');
  // Both secondary actions must reopen this wizard rather than generic MCP credentials.
  for(const action of ['Bearbeiten','Zugang prüfen']){
   await more();await row.getByRole('button',{name:action,exact:true}).click();await name.waitFor();
   if(await page.getByRole('dialog',{name:'Verbindung bearbeiten',exact:true}).count())throw Error('Proton setup opened generic MCP credentials');
   if(await password.inputValue()!=='')throw Error('Stored password populated into wizard');
   await wizard.getByRole('button',{name:'Einrichtung schließen',exact:true}).click();await wizard.waitFor({state:'hidden'});
  }
  if(posts.length!==2)throw Error('Secondary setup navigation automatically rechecked mailbox');
  await openRow();await password.fill('synthetic-unsaved-password');await page.keyboard.press('Escape');await wizard.waitFor({state:'hidden'});
  if(await page.locator('.shell').evaluate(el=>el.inert))throw Error('Wizard left workspace inert after Escape');
  await openRow();if(await password.inputValue()!=='')throw Error('Wizard close retained unsaved credentials');
  if(process.env.HUB_PROTON_BRIDGE_CAPTURE){await page.evaluate(()=>document.activeElement?.blur());await wizard.screenshot({path:process.env.HUB_PROTON_BRIDGE_CAPTURE})}
  const beforeFailureGets=getCount;
  await password.fill('synthetic-invalid-password');await review();await Promise.all([page.waitForResponse(r=>r.url()===endpoint&&r.request().method()==='GET'),submit.click()]);await wizard.getByRole('alert').waitFor();await name.waitFor();
  if(posts.length!==3||getCount<=beforeFailureGets||await password.inputValue()!=='')throw Error('Failed setup did not return to credentials, clear password and refresh revision');
  await review();await success();
  if(posts.length!==4||posts[3].expected_revision!==profile.revision+3||posts[3].password!==null)throw Error('Explicit setup retry used stale state');
  await row.getByText('Verbunden',{exact:true}).waitFor();
  // Activation invalidates profile authority; it must never submit/regrant credentials itself.
  const activation=row.getByRole('switch',{name:'Integration Proton Mail Aurora aktivieren',exact:true});
  for(const desired of [false,true]){
   const beforeControlGets=getCount;
   await Promise.all([page.waitForResponse(r=>r.url()===endpoint&&r.request().method()==='GET'),activation.click()]);
   await page.waitForFunction(value=>document.querySelector('.registry-switch[aria-label="Integration Proton Mail Aurora aktivieren"]')?.getAttribute('aria-checked')===String(value),desired);
   if(getCount<=beforeControlGets||enabled!==desired||await activation.getAttribute('aria-checked')!==String(desired))throw Error('Proton activation did not refresh setup authority');
   if(await row.getByText('Verbunden',{exact:true}).count()||posts.length!==4)throw Error('Activation retained connection authority or automatically performed setup');
  }
  const currentRevision=state.revision;await openRow();
  if(await reads.isChecked())throw Error('Activation retained stale read grants');
  await page.setViewportSize({width:320,height:740});
  if(await wizard.evaluate(el=>el.scrollWidth>el.clientWidth+1||el.getBoundingClientRect().right>innerWidth+1)||await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Proton wizard mobile overflow');
  await page.setViewportSize({width:1440,height:1100});
  await reads.check();await review();await success();
  if(posts.length!==5||posts[4].expected_revision!==currentRevision||posts[4].password!==null)throw Error('Wizard did not use refreshed activation revision');
  await row.getByText('Verbunden',{exact:true}).waitFor();
  console.log('Proton wizard UI passed: explicit add-provider entry, guided preparation/credentials/review, no automatic mailbox calls, masked secrets, preserved read choice, blank stored password, back/Escape clearing, secondary actions, failed-attempt refresh and explicit retry, activation authority refresh and mobile layout.');
 }finally{
  await page.unroute(endpoint,setupRoute);await page.unroute(registry,registryRoute);await page.unroute(controlEndpoint,controlRoute);
  const current=(await call('/integrations')).integrations.find(row=>row.id===profile.id);
  if(current)await call('/integrations/'+profile.id,'DELETE',{expected_revision:current.revision});
 }
}
