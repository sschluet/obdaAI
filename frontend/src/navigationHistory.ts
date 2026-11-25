import {guardNavigation,hasUnsavedChanges} from './NavigationGuard';
const positionKey='hubNavigationPosition';
/** Keep native Back/Forward entries intact while an unsaved editor asks to leave. */
export class NavigationHistory {
 private position=Number.isInteger(history.state?.[positionKey])?history.state[positionKey] as number:0;
 private currentURL=location.href;
 private restored:(()=>void)|null=null;
 mark(){this.currentURL=location.href;history.replaceState({...history.state,[positionKey]:this.position},'',location.href)}
 navigate(url:string,replace=false){
  if(!replace)this.position++;
  const state={...history.state,[positionKey]:this.position};
  if(replace)history.replaceState(state,'',url);else history.pushState(state,'',url);
  this.currentURL=location.href;
 }
 pop(run:()=>void){
  if(this.restored){const resolve=this.restored;this.restored=null;resolve();return}
  const destination=location.href;
  const target=Number.isInteger(history.state?.[positionKey])?history.state[positionKey] as number:null;
  if(!hasUnsavedChanges()){if(target!==null)this.position=target;this.mark();run();return}
  const delta=target===null?0:target-this.position;
  if(delta){
   // Return to the original entry first. A later approval traverses the same entry once.
   const returned=new Promise<void>(resolve=>{this.restored=resolve});history.go(-delta);
   guardNavigation(()=>{void returned.then(()=>history.go(delta))});
  }else{
   // Old/unmarked links can still be protected without inserting or truncating entries.
   history.replaceState({...history.state,[positionKey]:this.position},'',this.currentURL);
   guardNavigation(()=>{history.replaceState({...history.state,[positionKey]:this.position},'',destination);this.currentURL=destination;run()});
  }
 }
}
