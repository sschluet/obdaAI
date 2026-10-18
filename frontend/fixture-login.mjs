// UI authentication only for isolated synthetic fixtures; retain app rate limits.
export async function loginFixture(page,password='synthetic-ui-password'){
 const origin=new URL(page.url()).origin;
 if(!['http://127.0.0.1:18765','http://127.0.0.1:18767','http://127.0.0.1:18769'].includes(origin))throw Error('Refusing login outside the isolated fixture');
 for(let attempt=0;attempt<3;attempt++){
  await page.getByLabel('Passwort',{exact:true}).fill(password);
  const response=page.waitForResponse(r=>r.url()===origin+'/api/login'&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Anmelden',exact:true}).click();
  const result=await response;
  if(result.ok()){const body=await result.json();await page.getByRole('button',{name:'Abmelden',exact:true}).waitFor();return body;}
  if(result.status()!==429)throw Error('Synthetic fixture login failed: '+result.status());
  const seconds=Math.min(60,Math.max(1,Number(result.headers()['retry-after'])||60));
  console.log('Fixture login rate-limited; respecting the app cooldown.');
  await new Promise(resolve=>setTimeout(resolve,(seconds+1)*1000));
 }
 throw Error('Fixture login remains rate-limited after bounded retries');
}
