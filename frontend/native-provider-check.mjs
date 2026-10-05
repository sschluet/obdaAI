// Synthetic settings UI only; no paid native request.
import {chromium} from 'playwright';
import {mkdir} from 'node:fs/promises';
const output='../.local/browser';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:390,height:844}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('http://127.0.0.1:18765');
 await page.getByLabel('Passwort',{exact:true}).fill('synthetic-ui-password');
 await page.getByRole('button',{name:'Anmelden',exact:true}).click();
 await page.getByRole('button',{name:'Navigation öffnen',exact:true}).click();
 await page.getByRole('button',{name:'Einstellungen',exact:true}).click();
 await page.getByRole('button',{name:'Modelle',exact:true}).click();
 for(const [kind,label,model] of [['openai','OpenAI direkt','gpt-4.1-mini'],['anthropic','Anthropic direkt','claude-haiku-4-5-20251001']]){
  await page.getByRole('button',{name:'Modellverbindung hinzufügen',exact:true}).click();
  const form=page.locator('.provider-form');
  await form.getByLabel('Name der Verbindung').fill('Synthetic '+label+' '+Date.now());
  await form.getByLabel('Typ',{exact:true}).selectOption(kind);
  if(await form.getByLabel('Modellkennung').inputValue()!==model)throw Error('Missing native model suggestion');
  await form.getByText('Verbindung kann vorbereitet werden.',{exact:false}).waitFor();
  await form.getByRole('button',{name:'Speichern',exact:true}).click();
  await form.waitFor({state:'hidden'});
  const card=page.locator('.provider-grid article').filter({hasText:'Synthetic '+label}).last();
  await card.waitFor();
  if(!await card.getByRole('button',{name:'Verbindung testen',exact:true}).isDisabled())throw Error('Unapproved native target can be tested');
 }
 await page.screenshot({path:output+'/native-provider-mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2))throw Error('Mobile overflow');
 if(errors.length)throw Error(errors.join('; '));
 console.log('Native provider mobile UI passed: fixed endpoints, model suggestions, disabled external tests. Synthetic only.');
}finally{await browser.close()}
