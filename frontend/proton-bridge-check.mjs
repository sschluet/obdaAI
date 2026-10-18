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
  const panel=page.getByRole('region',{name:'Proton Mail verbinden',exact:true});
  const name=panel.getByLabel('Name der Verbindung',{exact:true}), username=panel.getByLabel('Bridge-Benutzername',{exact:true}), password=panel.getByLabel('Bridge-Passwort',{exact:true});
  const reads=panel.getByLabel('Lokales Lesen und Suchen über Chat, Aufgaben und Projekte erlauben',{exact:true});
  const submit=panel.getByRole('button',{name:'Verbindung prüfen und speichern',exact:true});
  await name.waitFor();
  if(await password.getAttribute('type')!=='password'||await password.inputValue()!==''||await panel.locator('input').count()!==4)throw Error('Proton setup exposes credentials or unexpected login fields');
  await name.fill('Proton Mail Aurora');await username.fill('aurora@example.test');await password.fill('synthetic-bridge-password');await reads.uncheck();
  if((await panel.innerText()).includes('synthetic-bridge-password'))throw Error('Bridge password rendered as text');
  await submit.click();await panel.getByText('Postfachverbindung gespeichert und geprüft.',{exact:true}).waitFor();
  if(posts.length!==1||posts[0].password!=='synthetic-bridge-password'||posts[0].enable_reads!==false||await password.inputValue()!=='')throw Error('Proton setup initial credential/read choice failed');
  await reads.check();await submit.click();await submit.waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('.proton-bridge-setup input[type=password]')?.value==='');
  if(posts.length!==2||posts[1].password!==null||posts[1].enable_reads!==true||posts[1].expected_revision!==profile.revision+1)throw Error('Proton setup did not preserve stored Bridge password on blank update');
  // Both registry actions must reopen this Bridge form, rather than the generic MCP token dialog.
  const row=page.locator('.registry-table tr').filter({hasText:'Proton Mail Aurora'});
  for(const action of ['Bearbeiten','Zugang prüfen']){
   await panel.getByRole('button',{name:'Einrichtung schließen',exact:true}).click();
   await row.getByRole('button',{name:action,exact:true}).click();await name.waitFor();
   if(await page.getByRole('dialog',{name:'Verbindung bearbeiten',exact:true}).count())throw Error('Proton setup opened generic MCP credentials');
  }
  if(process.env.HUB_PROTON_BRIDGE_CAPTURE){await page.setViewportSize({width:1440,height:1800});await panel.scrollIntoViewIfNeeded();await panel.screenshot({path:process.env.HUB_PROTON_BRIDGE_CAPTURE});await page.setViewportSize({width:1440,height:1100})}
  const beforeFailureGets=getCount;
  await password.fill('synthetic-invalid-password');await submit.click();await panel.getByRole('alert').waitFor();await submit.waitFor({state:'visible'});
  if(posts.length!==3||getCount<=beforeFailureGets||await password.inputValue()!=='')throw Error('Failed Proton setup did not clear password and reload revision');
  if(posts.length!==3)throw Error('Failed Proton setup automatically retried');
  await submit.click();await panel.getByText('Postfachverbindung gespeichert und geprüft.',{exact:true}).waitFor();
  if(posts.length!==4||posts[3].expected_revision!==profile.revision+3||posts[3].password!==null)throw Error('Explicit Proton setup retry used stale state');
  await row.getByText('Verbunden',{exact:true}).waitFor();
  // Generic activation changes profile authority and must refresh the Bridge form too.
  const activation=row.getByRole('switch',{name:'Integration Proton Mail Aurora aktivieren',exact:true});
  for(const desired of [false,true]){
   const beforeControlGets=getCount;
   await Promise.all([page.waitForResponse(r=>r.url()===endpoint&&r.request().method()==='GET'),activation.click()]);
   await page.waitForFunction(value=>document.querySelector('.registry-switch[aria-label="Integration Proton Mail Aurora aktivieren"]')?.getAttribute('aria-checked')===String(value),desired);
   await page.waitForFunction(()=>document.querySelector('.proton-bridge-setup input[type=checkbox]')?.checked===false);
   if(getCount<=beforeControlGets||enabled!==desired||await activation.getAttribute('aria-checked')!==String(desired))throw Error('Proton activation did not refresh setup authority');
   if(await row.getByText('Verbunden',{exact:true}).count())throw Error('Stale Proton profile displayed as connected after activation');
   if(await reads.isChecked())throw Error('Proton activation retained stale read grants');
  }
  const currentRevision=state.revision;
  await reads.check();await submit.click();
  await panel.getByText('Postfachverbindung gespeichert und geprüft.',{exact:true}).waitFor();
  await submit.waitFor({state:'visible'});
  if(posts.length!==5||posts[4].expected_revision!==currentRevision||posts[4].password!==null)throw Error('Proton setup did not use refreshed activation revision');
  await row.getByText('Verbunden',{exact:true}).waitFor();
  await page.setViewportSize({width:320,height:740});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Proton setup mobile overflow');
  await page.setViewportSize({width:1440,height:1100});
  console.log('Proton Bridge UI contract passed: masked Bridge credentials, explicit read choice, blank password preservation, revision/request binding, registry setup actions, failure refresh and explicit retry, activation authority refresh, mobile layout.');
 }finally{
  await page.unroute(endpoint,setupRoute);await page.unroute(registry,registryRoute);await page.unroute(controlEndpoint,controlRoute);
  const current=(await call('/integrations')).integrations.find(row=>row.id===profile.id);
  if(current)await call('/integrations/'+profile.id,'DELETE',{expected_revision:current.revision});
 }
}
