import assert from 'node:assert/strict';
import {loginFixture} from './fixture-login.mjs';
const result=(status,csrf)=>({url:()=> 'http://127.0.0.1:18765/api/login',request:()=>({method:()=> 'POST'}),ok:()=>status===200,status:()=>status,headers:()=>({}),json:async()=>({csrf})});
const responses=[result(429),result(200,'synthetic-csrf-after-cooldown')];
let clicks=0;const waits=[];
const page={url:()=> 'http://127.0.0.1:18765/',getByLabel:()=>({fill:async()=>{}}),getByRole:()=>({click:async()=>{clicks++},waitFor:async()=>{}}),waitForResponse:async predicate=>{const response=responses.shift();assert.ok(predicate(response));return response;}};
const timer=globalThis.setTimeout;
try{
 globalThis.setTimeout=(callback,milliseconds)=>{waits.push(milliseconds);callback();return 0;};
 const login=await loginFixture(page);
 assert.equal(login.csrf,'synthetic-csrf-after-cooldown');
 assert.equal(clicks,2);
 assert.deepEqual(waits,[61000]);
 await assert.rejects(loginFixture({...page,url:()=> 'https://example.org/'}),/Refusing login/);
 console.log('Fixture login passed: cooldown respected, successful retry CSRF retained, non-fixture targets rejected.');
}finally{globalThis.setTimeout=timer;}
