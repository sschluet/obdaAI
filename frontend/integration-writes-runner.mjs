// Invoked by the established generic integration check, including existing CI.
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {createConnection} from 'node:net';
const root=fileURLToPath(new URL('..',import.meta.url));
const origin='http://127.0.0.1:18767';
const occupied=await new Promise(resolve=>{const socket=createConnection({host:'127.0.0.1',port:18767});socket.once('connect',()=>{socket.destroy();resolve(true)});socket.once('error',()=>resolve(false))});
if(occupied)throw Error('Port 18767 is already in use; refusing to reuse or stop that server');
const fixtureId=randomUUID();
const fixture=spawn(join(root,'.venv/bin/python'),['-m','uvicorn','scripts.integration_write_fixture:app','--host','127.0.0.1','--port','18767','--no-access-log'],{cwd:root,stdio:['ignore','inherit','inherit'],env:{...process.env,HUB_BROWSER_ORIGIN:origin,HUB_WRITE_FIXTURE_ID:fixtureId,HUB_BROWSER_FIXTURE_DIR:'.local/integration-write-check-'+Date.now()}});
let closed=false,startError=null;fixture.once('error',e=>{startError=e});fixture.once('exit',()=>{closed=true});
try{
 let ready=false;
 for(let attempt=0;attempt<60;attempt++){
  if(startError)throw startError;
  if(closed)throw Error('Isolated write fixture could not start; do not reuse another server');
  try{const r=await fetch(origin+'/api/health');if(r.ok&&r.headers.get('X-OBDAAI-SYNTHETIC-FIXTURE')===fixtureId){ready=true;break}}catch{}
  await new Promise(resolve=>setTimeout(resolve,250));
 }
 if(!ready||closed)throw Error('Isolated write fixture health check failed');
 await new Promise((resolve,reject)=>{const test=spawn(process.execPath,['frontend/integration-writes-check.mjs'],{cwd:root,stdio:'inherit',env:{...process.env,HUB_WRITE_ORIGIN:origin}});test.on('error',reject);test.on('exit',code=>code===0?resolve():reject(Error('Integration write browser check failed: '+code)))});
}finally{
 if(!closed){fixture.kill('SIGTERM');await new Promise(resolve=>{const timer=setTimeout(resolve,5000);fixture.once('exit',()=>{clearTimeout(timer);resolve()})})}
}
