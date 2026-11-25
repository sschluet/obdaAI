// The optional explicit system path lives under +; ordinary prompts need no mode change.
export async function getSystemMode(page){
 await page.getByRole('button',{name:'Aktionen und Anhänge',exact:true}).click();
 const mode=page.getByRole('menuitemcheckbox',{name:'Systemauftrag',exact:true});
 await mode.waitFor();const enabled=(await mode.getAttribute('aria-checked'))==='true';
 await page.keyboard.press('Escape');return enabled;
}
export async function setSystemMode(page,enabled){
 await page.getByRole('button',{name:'Aktionen und Anhänge',exact:true}).click();
 const mode=page.getByRole('menuitemcheckbox',{name:'Systemauftrag',exact:true});await mode.waitFor();
 if(((await mode.getAttribute('aria-checked'))==='true')!==enabled)await mode.click();
 else await page.keyboard.press('Escape');
}
