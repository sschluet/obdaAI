// Offline snapshots only. No model code, network, stored cookies, forms or credentials.
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {chromium} from 'playwright';
const input='/browser-requests', output='/browser-results';
const idPattern=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const sha=s=>crypto.createHash('sha256').update(s).digest('hex');
async function regular(path,limit){const s=await fs.lstat(path);if(!s.isFile()||s.isSymbolicLink()||s.size>limit)throw Error('Invalid job');return fs.readFile(path,'utf8')}
async function processJob(file){
 const id=file.slice(0,-5);if(!idPattern.test(id))return;
 try{await fs.lstat(output+'/'+file);return}catch(e){if(e.code!=='ENOENT')throw e}
 let result,browser;
 try{
  const job=JSON.parse(await regular(input+'/'+file,1_100_000));
  if(Object.keys(job).sort().join(',')!=='html,id,sha256'||job.id!==id||typeof job.html!=='string'||Buffer.byteLength(job.html)>1_000_000||sha(job.html)!==job.sha256)throw Error('Invalid job');
  browser=await chromium.launch({headless:true,chromiumSandbox:true,timeout:10000});
  const context=await browser.newContext({javaScriptEnabled:false,serviceWorkers:'block',acceptDownloads:false,viewport:{width:1280,height:720},ignoreHTTPSErrors:false});
  await context.route('**/*',route=>route.abort());
  await context.routeWebSocket('**/*',socket=>socket.close());
  const page=await context.newPage();page.setDefaultTimeout(5000);
  page.on('dialog',dialog=>dialog.dismiss());page.on('popup',popup=>popup.close());
  const policy='<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;; script-src &#39;none&#39;; frame-src &#39;none&#39;; form-action &#39;none&#39;; base-uri &#39;none&#39;">';
  await page.setContent(policy+job.html,{waitUntil:'domcontentloaded',timeout:5000});
  const text=(await page.locator('body').innerText({timeout:5000})).slice(0,64000);
  const png=await page.screenshot({type:'png',fullPage:false,timeout:5000,animations:'disabled'});
  if(png.length>2_000_000)throw Error('Preview limit');
  result={id,sha256:job.sha256,text,png:png.toString('base64'),network:false,javascript:false};
 }catch{result={id,error:'Browserprüfung fehlgeschlagen; Isolation, Format und Limits prüfen'}}
 finally{if(browser)await browser.close()}
 const tmp=output+'/.'+id+'.tmp';await fs.writeFile(tmp,JSON.stringify(result),{mode:0o600});await fs.rename(tmp,output+'/'+file);
}
if(process.argv[2]){
 await processJob(process.argv[2]);
}else{
 while(true){
  for(const file of (await fs.readdir(input)).filter(f=>idPattern.test(f.slice(0,-5))&&f.endsWith('.json')).sort().slice(0,1000)){
   try{await fs.lstat(output+'/'+file);continue}catch(e){if(e.code!=='ENOENT')throw e}
   await new Promise(resolve=>{
    const child=spawn(process.execPath,[import.meta.filename,file],{detached:true,stdio:'ignore'});
    const timer=setTimeout(()=>{try{process.kill(-child.pid,'SIGKILL')}catch{}},35000);
    child.once('exit',async()=>{clearTimeout(timer);try{
     await fs.lstat(output+'/'+file);
    }catch(e){if(e.code==='ENOENT'){
     const id=file.slice(0,-5),temp=output+'/.'+id+'.failed';
     await fs.writeFile(temp,JSON.stringify({id,error:'Browserprüfung abgebrochen oder Zeitlimit erreicht'}),{mode:0o600});await fs.rename(temp,output+'/'+file);
    }}resolve()});
   });
  }
  await new Promise(resolve=>setTimeout(resolve,500));
 }
}
