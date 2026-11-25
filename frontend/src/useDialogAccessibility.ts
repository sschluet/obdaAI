import {useEffect,useRef,useState,type RefObject} from 'react';
/** Shared keyboard/focus behavior for modal dialogs. Never disables the dialog itself. */
export function useDialogAccessibility(ref:RefObject<HTMLElement|null>,open:boolean,onClose:()=>void,busy=false,identity:unknown=open){
 const close=useRef(onClose);close.current=onClose;
 useEffect(()=>{if(!open)return;const dialog=ref.current;if(!dialog)return;dialog.dataset.hubDialogKeyboard='true';const previous=document.activeElement as HTMLElement|null;const changed:HTMLElement[]=[];
 let branch:HTMLElement=dialog;while(branch.parentElement&&branch.parentElement!==document.documentElement){for(const sibling of Array.from(branch.parentElement.children)){if(sibling!==branch&&sibling instanceof HTMLElement&&!sibling.inert&&!['SCRIPT','STYLE','LINK'].includes(sibling.tagName)){sibling.inert=true;changed.push(sibling)}}branch=branch.parentElement}
 const controls=()=>Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],summary,[tabindex="0"]')).filter(item=>item.getClientRects().length>0);
 // Existing dialogs may deliberately focus their heading/container before their controls.
 if(!dialog.contains(document.activeElement))(controls()[0]||dialog).focus();
 const key=(event:KeyboardEvent)=>{if(dialog.closest('[inert]'))return;if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(!busy)close.current()}if(event.key==='Tab'){const items=controls(),first=items[0],last=items.at(-1);if(!first){event.preventDefault();dialog.focus()}else if(event.shiftKey&&(document.activeElement===first||!dialog.contains(document.activeElement))){event.preventDefault();last?.focus()}else if(!event.shiftKey&&(document.activeElement===last||!dialog.contains(document.activeElement))){event.preventDefault();first.focus()}}};document.addEventListener('keydown',key,true);
 return()=>{document.removeEventListener('keydown',key,true);for(const node of changed)node.inert=false;requestAnimationFrame(()=>{if(previous?.isConnected&&!previous.closest('[inert]'))previous.focus()})};
 },[open,busy,ref,identity]);
}

/** Bring older modal forms onto the same keyboard contract without changing their API. */
export function useLegacyDialogAccessibility(){
 const [dialog,setDialog]=useState<HTMLElement|null>(null),ref=useRef<HTMLElement|null>(null);ref.current=dialog;
 useEffect(()=>{const inspect=()=>{const candidates=Array.from(document.querySelectorAll<HTMLElement>('.modal>form,.modal>div')).filter(node=>node.dataset.dialogInline!=='true'&&node.dataset.dialogOwned!=='true'&&(node.dataset.hubDialogKeyboard!=='true'||node.dataset.dialogManaged==='true'));setDialog(candidates.at(-1)||null)};inspect();const observer=new MutationObserver(inspect);observer.observe(document.body,{childList:true,subtree:true});return()=>observer.disconnect()},[]);
 useEffect(()=>{if(!dialog)return;dialog.dataset.dialogManaged='true';dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');dialog.setAttribute('tabindex','-1');if(!dialog.hasAttribute('aria-label'))dialog.setAttribute('aria-label',dialog.querySelector('h2,h3')?.textContent||'Bearbeiten')},[dialog]);
 useDialogAccessibility(ref,!!dialog,()=>{const buttons=Array.from(dialog?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')||[]);buttons.find(button=>/^(Abbrechen|Schließen|Weiter bearbeiten)$/.test(button.textContent?.trim()||'')||/schließen/i.test(button.getAttribute('aria-label')||''))?.click()},false,dialog);
}
