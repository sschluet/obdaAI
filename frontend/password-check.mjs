// Rotates and restores only the isolated local synthetic fixture password.
import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';
const base='http://127.0.0.1:18765',original='synthetic-ui-password',replacement='synthetic-password-change-verification';
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),second=await browser.newContext();
const page=await context.newPage(),other=await second.newPage();
let rotated=false,changes=0;const errors=[];page.on('pageerror',e=>errors.push(e.message));
page.on('request',request=>{if(request.url()===base+'/api/account/password'&&request.method()==='POST')changes++});
async function credentials(current,next,confirm=next){await page.getByLabel('Aktuelles Passwort',{exact:true}).fill(current);await page.getByLabel('Neues Passwort',{exact:true}).fill(next);await page.getByLabel('Neues Passwort bestätigen',{exact:true}).fill(confirm)}
async function fixtureLoginRequest(request,password){for(let attempt=0;attempt<3;attempt++){const result=await request.post(base+'/api/login',{headers:{Origin:base},data:{password}});if(result.status()!==429)return result;const seconds=Math.min(60,Math.max(1,Number(result.headers()['retry-after'])||60));await new Promise(resolve=>setTimeout(resolve,(seconds+1)*1000))}throw Error('Fixture login rate limit persisted')}
try{
 await page.goto(base);await loginFixture(page);await other.goto(base);await loginFixture(other);
 await page.getByRole('button',{name:'Einstellungen',exact:true}).click();await page.getByRole('button',{name:'Sicherheit',exact:true}).click();
 await credentials(original,'short');if(!await page.getByRole('button',{name:'Passwortänderung prüfen',exact:true}).isDisabled())throw Error('Short password allowed');
 await credentials(original,replacement,'synthetic-mismatch-value');if(!await page.getByRole('button',{name:'Passwortänderung prüfen',exact:true}).isDisabled())throw Error('Mismatched confirmation allowed');
 await credentials(original,replacement);await page.getByRole('button',{name:'Passwortänderung prüfen',exact:true}).click();await page.getByRole('group',{name:'Passwortänderung bestätigen',exact:true}).waitFor();if(changes)throw Error('Review changed password before explicit confirmation');
 await page.getByRole('button',{name:'Zurück',exact:true}).click();if(changes||await page.getByRole('group',{name:'Passwortänderung bestätigen',exact:true}).count())throw Error('Cancelled review posted password');
 await credentials('synthetic-wrong-current',replacement);await page.getByRole('button',{name:'Passwortänderung prüfen',exact:true}).click();await page.getByRole('button',{name:'Passwort ändern und neu anmelden',exact:true}).click();await page.getByRole('alert').waitFor();if((await other.request.get(base+'/api/me')).status()!==200)throw Error('Failed change invalidated another session');
 await credentials(original,replacement);await page.setViewportSize({width:390,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Password settings mobile overflow');
 await page.getByRole('button',{name:'Passwortänderung prüfen',exact:true}).click();const pending=page.waitForResponse(r=>r.url()===base+'/api/account/password'&&r.request().method()==='POST');await page.getByRole('button',{name:'Passwort ändern und neu anmelden',exact:true}).click();const changed=await pending;rotated=changed.ok();if(!rotated)throw Error('Password change failed: '+changed.status());
 await page.getByLabel('Passwort',{exact:true}).waitFor();if(await page.getByLabel('Passwort',{exact:true}).inputValue())throw Error('Password remained in login input');await page.getByRole('status').filter({hasText:'Passwort geändert'}).waitFor();
 if((await other.request.get(base+'/api/me')).status()!==401||(await page.request.get(base+'/api/me')).status()!==401)throw Error('Session still authenticated after change');
 if((await fixtureLoginRequest(page.request,original)).status()!==401)throw Error('Old password still accepted');
 await loginFixture(page,replacement);await page.getByRole('button',{name:'Abmelden',exact:true}).waitFor();
 if(errors.length)throw Error(errors.join('\n'));
}finally{
 try{if(rotated){const restoreContext=await browser.newContext();try{const login=await fixtureLoginRequest(restoreContext.request,replacement);if(!login.ok())throw Error('Cannot authenticate synthetic restore');const csrf=(await login.json()).csrf;const restore=await restoreContext.request.post(base+'/api/account/password',{headers:{Origin:base,'X-CSRF-Token':csrf},data:{current_password:replacement,new_password:original,confirm_password:original}});if(!restore.ok())throw Error('Synthetic password restoration failed: '+restore.status())}finally{await restoreContext.close()}}}finally{await browser.close()}
}
console.log('Password UX passed: validation, explicit confirmation/cancel, wrong-current rejection, mobile, all-session invalidation, old/new login. Synthetic fixture password restored.');
