// Synthetic OAuth contract only: Google navigation is fulfilled by an inert fixture before network access.
export async function checkGmailSetup({page, base, call}) {
 const profile=await call('/integrations','POST',{name:'Gmail Aurora',kind:'mcp',url:'https://gmail.example.test/mcp',auth:'none',protocol:'2026-07-28'});
 const policy=await call('/integrations/'+profile.id+'/agent-policy');
 const metadata=base+'/api/integrations/gmail/setup';
 const profileEndpoint=base+'/api/integrations/gmail/'+profile.id;
 const registry=base+'/api/integrations';
 const redirect='https://hub.example.test/api/integrations/gmail/callback';
 let state={available:true,integration_id:null,revision:0,name:'Gmail Aurora',client_id:'',client_secret_saved:false,configured:false,connected:false,enabled:false,enable_reads:false,account_email:'',redirect_uri:redirect,scopes:['https://www.googleapis.com/auth/gmail.readonly'],network_ready:true,message:''};
 const posts=[], authorizations=[], disconnections=[], googleRequests=[];let setupGets=0;
 const setupRoute=async route=>{
  if(route.request().method()==='GET'){
   setupGets++;const id=new URL(route.request().url()).searchParams.get('integration_id');
   if(id&&id!==profile.id)throw Error('Gmail setup selected a different fixture profile');
  }else{
   const data=route.request().postDataJSON();posts.push(data);
   if(data.integration_id!==state.integration_id||data.expected_revision!==(state.integration_id?state.revision:null)||typeof data.enable_reads!=='boolean'||!data.request_id)throw Error('Gmail client save omitted revision/request/read binding');
   if(data.client_secret==='synthetic-rejected'){await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Synthetische Client-Prüfung fehlgeschlagen.'})});return}
   if(!data.client_secret&&(!state.client_secret_saved||data.client_id!==state.client_id))throw Error('Gmail blank secret preserved across a different client');
   state={...state,integration_id:profile.id,revision:state.revision+1,name:data.name,client_id:data.client_id,client_secret_saved:true,configured:true,connected:false,enabled:false,enable_reads:data.enable_reads};
  }
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(state)});
 };
 const registryRoute=async route=>{
  if(route.request().method()!=='GET'){await route.continue();return}
  const response=await route.fetch(), data=await response.json();
  data.integrations=data.integrations.map(row=>row.id===profile.id?{...row,name:state.name,kind:'gmail',revision:state.revision,enabled:state.enabled,config:{url:'https://gmail.googleapis.com',auth:'oauth',connected:state.connected,account_email:state.account_email},last_check:state.connected?{revision:state.revision,created:1700000000,status:'succeeded'}:null}:row);
  await route.fulfill({response,json:data}).catch(error=>{if(!String(error).includes('Route is already handled'))throw error;});
 };
 const policyEndpoint=base+'/api/integrations/'+profile.id+'/agent-policy';
 const policyRoute=async route=>{await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...policy,current:true,profile_revision:state.revision,writes_enabled:false,rules:{...policy.rules,enabled:state.enabled&&state.enable_reads,gmail_read:state.enable_reads,private_data_to_target:state.enable_reads,max_effects:0}})});};
 const authorizeRoute=async route=>{
  const data=route.request().postDataJSON();authorizations.push(data);
  if(data.expected_revision!==state.revision||!data.request_id)throw Error('Gmail OAuth omitted its explicit revision/request binding');
  state={...state,revision:state.revision+1,connected:false,enabled:false};
  const url=new URL('https://accounts.google.com/o/oauth2/v2/auth');
  url.search=new URLSearchParams({client_id:state.client_id,response_type:'code',state:'synthetic-once',redirect_uri:redirect,scope:state.scopes[0]}).toString();
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({authorization_url:url.href,auth_url:url.href,expires_at:2000000000,revision:state.revision})});
 };
 const disconnectRoute=async route=>{
  const data=route.request().postDataJSON();disconnections.push(data);
  if(data.expected_revision!==state.revision||data.revoke_google!==false)throw Error('Gmail disconnect changed its scope or used stale revision');
  state={...state,revision:state.revision+1,connected:false,enabled:false,enable_reads:false,account_email:''};
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...state,google_revoke_status:'not_requested'})});
 };
 const externalGuard=async route=>{
  const url=new URL(route.request().url());
  if(url.origin===new URL(base).origin){await route.continue();return}
  if(url.origin==='https://accounts.google.com'&&url.pathname==='/o/oauth2/v2/auth'){
   googleRequests.push(url.href);
   await route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><title>Synthetic OAuth interception</title><h1>Synthetic OAuth navigation intercepted</h1>'});return;
  }
  await route.abort('blockedbyclient');
 };
 await page.route(metadata+'**',setupRoute);await page.route(registry,registryRoute);await page.route(policyEndpoint,policyRoute);
 await page.route(profileEndpoint+'/authorize',authorizeRoute);await page.route(profileEndpoint+'/disconnect',disconnectRoute);
 await page.context().route('**/*',externalGuard);
 try{
  await page.goto(base+'/?view=Einstellungen&settingsTab=Integrationen');await page.waitForLoadState('networkidle');
  if(setupGets||posts.length||authorizations.length)throw Error('Gmail setup contacted its API before explicit opening');
  await page.getByRole('button',{name:'Verbindung hinzufügen',exact:true}).click();
  await page.getByRole('button',{name:/^Gmail/}).click();
  const wizard=page.getByRole('dialog',{name:'Gmail einrichten',exact:true});
  await wizard.getByRole('heading',{name:'1. Google Cloud vorbereiten',exact:true}).waitFor();
  if(await wizard.getByLabel('Autorisierte Weiterleitungs-URI',{exact:true}).inputValue()!==redirect)throw Error('Gmail prep did not use exact server redirect URI');
  if(process.env.HUB_GMAIL_CAPTURE){await page.evaluate(()=>document.activeElement?.blur());await wizard.screenshot({path:process.env.HUB_GMAIL_CAPTURE});}
  await wizard.getByRole('button',{name:'OAuth-Client ist vorbereitet',exact:true}).click();
  const name=wizard.getByLabel('Name der Verbindung',{exact:true}), client=wizard.getByLabel('Google-Client-ID',{exact:true}), secret=wizard.getByLabel('Google-Client-Secret',{exact:true});
  const reads=wizard.getByLabel('Gmail lokal lesen und durchsuchen',{exact:true});
  await name.fill('Gmail Aurora');await client.fill('synthetic.apps.googleusercontent.com');await secret.fill('synthetic-rejected');
  if(await secret.getAttribute('type')!=='password'||!await reads.isChecked())throw Error('Gmail secret/read choice missing');
  await wizard.getByRole('button',{name:'Zugang speichern und weiter',exact:true}).click();
  await wizard.getByRole('alert').waitFor();
  if(await secret.inputValue()!==''||posts.length!==1||authorizations.length)throw Error('Gmail rejected client was retried, exposed or authorized');
  await secret.fill('synthetic-google-client-secret');await reads.uncheck();
  await wizard.getByRole('button',{name:'Zugang speichern und weiter',exact:true}).click();
  await wizard.getByRole('heading',{name:'3. Mit Google verbinden',exact:true}).waitFor();
  if(posts.length!==2||posts[1].enable_reads!==false||authorizations.length||await wizard.getByText(/^Verbunden/).count())throw Error('Saving Gmail client pretended authorization or widened reads');
  if((await wizard.innerText()).includes('synthetic-google-client-secret'))throw Error('Gmail secret displayed in summary');
  await wizard.getByRole('button',{name:'OAuth-Zugang bearbeiten',exact:true}).click();
  if(await secret.inputValue()!==''||await secret.getAttribute('required')!==null)throw Error('Gmail saved secret was not safely retained');
  await reads.check();await wizard.getByRole('button',{name:'Zugang speichern und weiter',exact:true}).click();
  await wizard.getByRole('heading',{name:'3. Mit Google verbinden',exact:true}).waitFor();
  if(posts.length!==3||posts[2].client_secret!==null||!posts[2].enable_reads)throw Error('Gmail same-client blank secret or explicit read consent lost');
  await Promise.all([page.waitForURL(url=>url.origin==='https://accounts.google.com'&&url.pathname==='/o/oauth2/v2/auth'),wizard.getByRole('button',{name:'Mit Google verbinden',exact:true}).click()]);
  await page.getByRole('heading',{name:'Synthetic OAuth navigation intercepted',exact:true}).waitFor();
  if(authorizations.length!==1)throw Error('Google OAuth was not bound to a single explicit action');
  if(googleRequests.length!==1||googleRequests[0].includes('synthetic-google-client-secret'))throw Error('Google navigation was not intercepted or exposed a secret');
  // Simulate a successful backend callback only in this fixture; no Google account is used.
  state={...state,revision:state.revision+1,connected:true,enabled:true,enable_reads:true,account_email:'aurora@example.test'};
  await page.goto(base+'/?view=Einstellungen&settingsTab=Integrationen#gmail_result=connected&gmail_integration='+profile.id);
  await wizard.getByRole('heading',{name:'Gmail ist verbunden',exact:true}).waitFor();
  if(page.url().includes('gmail_result='))throw Error('Gmail callback marker was not removed after opening status');
  await wizard.getByRole('button',{name:'Gmail-Einrichtung schließen',exact:true}).click();
  const row=page.locator('.registry-table tr').filter({hasText:'Gmail Aurora'});
  await row.getByRole('button',{name:'Postfach verwalten',exact:true}).waitFor();
  await row.getByText('Nur lesen',{exact:true}).waitFor();
  if(process.env.HUB_GMAIL_REGISTRY_CAPTURE)await page.locator('.integration-registry').screenshot({path:process.env.HUB_GMAIL_REGISTRY_CAPTURE});
  await row.getByRole('button',{name:'Postfach verwalten',exact:true}).click();
  await wizard.getByRole('heading',{name:'Gmail ist verbunden',exact:true}).waitFor();
  if(!((await wizard.innerText()).includes('aurora@example.test'))||authorizations.length!==1||posts.length!==3)throw Error('Opening Gmail status contacted Google or changed credentials');
  await page.setViewportSize({width:320,height:740});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)||await wizard.evaluate(element=>element.scrollWidth>element.clientWidth+1))throw Error('Gmail wizard mobile overflow');
  await page.setViewportSize({width:1440,height:1100});
  await wizard.getByText('Verbindung trennen',{exact:true}).click();
  await wizard.getByRole('button',{name:'Postfachzugriff in obdaAI trennen',exact:true}).click();
  await wizard.getByText('Der gespeicherte Postfachzugriff wurde in obdaAI getrennt.',{exact:true}).waitFor();
  if(disconnections.length!==1||state.connected)throw Error('Gmail local disconnect failed');
  await page.keyboard.press('Escape');await wizard.waitFor({state:'hidden'});
  if(await page.locator('.shell').evaluate(element=>element.inert))throw Error('Gmail modal left app inert');
  console.log('Gmail wizard synthetic UI passed: Cloud prep, exact redirect, masked client secret, explicit read consent, no authorization on save, blank-secret preservation, Google navigation intercepted before network, callback hash/status, local disconnect and mobile.');
 }finally{
  if(!page.url().startsWith(base+'/'))await page.goto(base+'/?view=Einstellungen&settingsTab=Integrationen');
  await page.waitForLoadState('networkidle').catch(()=>{});
  await page.unrouteAll({behavior:'wait'});
  await page.unroute(metadata+'**',setupRoute);await page.unroute(registry,registryRoute);
  await page.unroute(profileEndpoint+'/authorize',authorizeRoute);await page.unroute(profileEndpoint+'/disconnect',disconnectRoute);await page.context().unroute('**/*',externalGuard);
  const current=(await call('/integrations')).integrations.find(row=>row.id===profile.id);
  if(current)await call('/integrations/'+profile.id,'DELETE',{expected_revision:current.revision});
 }
}
