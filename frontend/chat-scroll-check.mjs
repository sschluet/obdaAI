import {chromium} from 'playwright';
import {loginFixture} from './fixture-login.mjs';

// Delayed provider chunks pass through the real API/SSE reader, not a buffered route.fulfill.
const base='http://127.0.0.1:18765';
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:900}});
const errors=[];
page.on('pageerror',error=>errors.push(error.message));
const region=page.getByRole('region',{name:'Gespräch',exact:true});
const endButton=()=>page.getByRole('button',{name:'Zum Ende',exact:true});
const metrics=()=>region.evaluate(el=>({top:el.scrollTop,height:el.scrollHeight,viewport:el.clientHeight,gap:el.scrollHeight-el.clientHeight-el.scrollTop,window:window.scrollY}));
async function waitForGrowth(height){await page.waitForFunction(previous=>{const el=document.querySelector('.chat-scroll');return el&&el.scrollHeight>previous+100},height);}
async function wheel(delta){const before=await metrics();await region.hover({position:{x:120,y:180}});await page.mouse.wheel(0,delta);await page.waitForFunction(previous=>document.querySelector('.chat-scroll').scrollTop<previous-1,before.top);await page.waitForTimeout(80);}
async function stableWhileGrowing(label){
 const before=await metrics();
 await waitForGrowth(before.height);
 const after=await metrics();
 if(Math.abs(after.top-before.top)>3)throw Error(label+': reader moved '+(after.top-before.top)+'px while answer grew');
 if(after.window!==0)throw Error(label+': document scrolled outside chat');
 await endButton().waitFor();
}
async function atEnd(label){await page.waitForFunction(()=>{const el=document.querySelector('.chat-scroll');return el&&el.scrollHeight-el.clientHeight-el.scrollTop<8});if((await metrics()).window!==0)throw Error(label+': outside document moved');}
async function start(){
 if(page.viewportSize().width<700)await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 const created=page.waitForResponse(response=>response.url()===base+'/api/conversations'&&response.request().method()==='POST'&&response.ok());
 await page.locator('button.new').click();
 const id=(await (await created).json()).id;
 await page.getByLabel('Nachricht',{exact:true}).fill('SYNTHETIC_LONG_STREAM_RESPONSE');
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).click();
 await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).waitFor();
 await page.waitForFunction(()=>{const el=document.querySelector('.chat-scroll');return el&&el.scrollHeight>el.clientHeight+500});
 await atEnd('Initial follow');
 return id;
}
try{
 await page.goto(base);await loginFixture(page);
 const chatId=await start();
 let before=await metrics();await waitForGrowth(before.height);await atEnd('Following new chunks');
 await wheel(-450);await stableWhileGrowing('Wheel up');
 // Retry/status changes and durable done/reload must not move the user's reading position.
 await endButton().focus();await page.keyboard.press('Enter');await atEnd('Explicit keyboard jump');
 if(!await region.evaluate(el=>document.activeElement===el))throw Error('Jump did not transfer focus back to the conversation');
 const afterJump=await metrics();await page.keyboard.press('PageUp');
 await page.waitForFunction(previous=>document.querySelector('.chat-scroll').scrollTop<previous,afterJump.top);await page.waitForTimeout(350);await stableWhileGrowing('Keyboard reader after jump');
 await endButton().click();await atEnd('Explicit jump resumes after keyboard reading');
 if(!await region.evaluate(el=>document.activeElement===el))throw Error('Pointer jump lost conversation focus');
 before=await metrics();await waitForGrowth(before.height);await atEnd('Follow after explicit jump');
 await wheel(-28);await stableWhileGrowing('Upward intent close to bottom');
 await region.evaluate(el=>{el.scrollTop=el.scrollHeight});await atEnd('Manual bottom');
 before=await metrics();await waitForGrowth(before.height);await atEnd('Follow after manual bottom');
 await wheel(-700);await stableWhileGrowing('Detached before completion');
 const detached=await metrics();
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).waitFor({timeout:25000});
 const completed=await metrics();
 if(Math.abs(completed.top-detached.top)>3)throw Error('Done/persisted reload changed detached reading position');
 await endButton().waitFor();
 // Keyboard navigation works without moving focus into the growing answer.
 await region.focus();await page.keyboard.press('Home');
 await page.waitForFunction(previous=>document.querySelector('.chat-scroll').scrollTop<previous,completed.top);await page.waitForTimeout(100);
 const keyboardPosition=await metrics();
 if(keyboardPosition.top>=completed.top)throw Error('Keyboard Home did not move upward');
 await page.keyboard.press('Tab');
 const tabPosition=await metrics();
 if(tabPosition.window!==0)throw Error('Keyboard focus scrolled whole document');
 // Trigger the existing retry action without Playwright first scrolling its below-fold button into view.
 await region.evaluate(el=>{el.scrollTop=0});await page.waitForTimeout(80);
 await page.getByRole('button',{name:'Antwort erneut erzeugen',exact:true}).evaluate(button=>button.click());
 await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).waitFor();
 await page.waitForFunction(()=>{const answer=document.querySelector('.message.assistant:last-of-type');const n=answer?.querySelectorAll('h3').length;return n>0&&n<10});
 await page.waitForFunction(()=>document.querySelector('.chat-scroll').scrollHeight>document.querySelector('.chat-scroll').clientHeight+500);
 if((await metrics()).top>3)throw Error('Retry forcibly resumed following at a detached reading position');
 await stableWhileGrowing('Retry while detached');
 await page.getByRole('button',{name:'Nachricht senden',exact:true}).waitFor({timeout:25000});
 if((await metrics()).top>3)throw Error('Retry completion moved detached reading position');
 await page.goto(base+'/?view=Chat&chat='+chatId);await page.locator('.message.assistant').waitFor();await atEnd('Opening completed conversation');
 // Compact touch-capable viewport and reduced motion use the same real delayed stream.
 await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});
 await start();await wheel(-350);await stableWhileGrowing('Mobile reader');
 const cdp=await page.context().newCDPSession(page);await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:true});
 const box=await region.boundingBox();const touch=(y)=>({x:box.x+box.width/2,y:box.y+y});
 await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[touch(80)]});
 await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[touch(160)]});
 await page.waitForTimeout(80);
 await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[touch(240)]});
 await page.waitForTimeout(100);
 await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
 await page.waitForTimeout(250);await stableWhileGrowing('Mobile touch reader');await cdp.detach();
 const beforeKey=await metrics();await region.focus();await page.keyboard.press(beforeKey.top>5?'PageUp':'PageDown');
 await page.waitForFunction(previous=>Math.abs(document.querySelector('.chat-scroll').scrollTop-previous)>2,beforeKey.top);await page.waitForTimeout(120);await stableWhileGrowing('Mobile keyboard reader');
 await endButton().click();await atEnd('Mobile explicit jump');
 before=await metrics();await waitForGrowth(before.height);await atEnd('Mobile follow resumed');
 await wheel(-300);await stableWhileGrowing('Detached before cancellation');const cancelPosition=await metrics();
 await page.getByRole('button',{name:'Antwort abbrechen',exact:true}).click();await page.getByRole('button',{name:'Nachricht senden',exact:true}).waitFor();
 const cancelled=await metrics();const expected=Math.min(cancelPosition.top,Math.max(0,cancelled.height-cancelled.viewport));
 if(Math.abs(cancelled.top-expected)>3)throw Error('Cancellation/status forcibly changed a still-available reading position');
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth||window.scrollY!==0))throw Error('Mobile chat overflow/outside scrolling');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Chat scroll UX passed: real delayed SSE follows at end, upward wheel intent detaches including near bottom, reading stays stable through chunks and completion, explicit/manual end resumes following, conversation open initializes end, retry preserves detached reading, keyboard/mobile touch/reduced-motion behavior, cancellation clamps only to available content and contained scrolling. Synthetic UI only.');
}finally{await browser.close()}
