import {useCallback,useLayoutEffect,useRef,useState} from 'react';

/** Collapse only after user scroll intent. Layout clamps and streaming never choose this state. */
export function useMobileChatChrome(container:HTMLElement|null,conversationKey:string,enabled:boolean){
 const [hidden,setHidden]=useState(false);const focusNavigation=useRef(false);
 const restoreNavigation=useCallback(()=>{focusNavigation.current=true;setHidden(false)},[]);
 useLayoutEffect(()=>{if(!hidden&&focusNavigation.current){focusNavigation.current=false;document.querySelector<HTMLElement>('.mobile-toggle')?.focus()}},[hidden]);
 const reveal=useCallback(()=>setHidden(false),[]);
 useLayoutEffect(()=>{
  setHidden(false);if(!container||!enabled)return;
  const media=matchMedia('(max-width:700px)');let lastTop=container.scrollTop,lastHeight=container.scrollHeight,lastViewport=container.clientHeight,armedUntil=0,touchY:number|null=null;
  const canHide=()=>media.matches&&!document.activeElement?.closest('.workspace>header,.chat-top,.workspace>.integration-binding-picker')&&!document.querySelector('.workspace>header details[open],.chat-top details[open],.workspace>.integration-binding-picker[open]');
  const intent=(direction:number)=>{if(direction<0){reveal();armedUntil=0}else if(direction>0){lastHeight=container.scrollHeight;lastViewport=container.clientHeight;armedUntil=performance.now()+700}};
  const nested=(target:EventTarget|null,delta:number)=>{for(let node=target instanceof Element?target:null;node&&node!==container;node=node.parentElement){const consume=delta<0?node.scrollTop>0:node.scrollHeight-node.clientHeight-node.scrollTop>1;if(consume&&node.scrollHeight>node.clientHeight+1&&['auto','scroll'].includes(getComputedStyle(node).overflowY))return true}return false};
  const scroll=()=>{const top=container.scrollTop,height=container.scrollHeight,viewport=container.clientHeight;if(top<=48)reveal();else if(height===lastHeight&&viewport===lastViewport&&performance.now()<armedUntil){if(top>lastTop+1&&top>100&&canHide())setHidden(true)}lastTop=top;lastHeight=height;lastViewport=viewport};
  const wheel=(event:WheelEvent)=>{if(!nested(event.target,event.deltaY))intent(event.deltaY)};
  const start=(event:TouchEvent)=>{touchY=event.touches[0]?.clientY??null};
  const move=(event:TouchEvent)=>{const y=event.touches[0]?.clientY;if(y!==undefined&&touchY!==null){const delta=touchY-y;if(Math.abs(delta)>2&&!nested(event.target,delta))intent(delta)}if(y!==undefined)touchY=y};
  const key=(event:KeyboardEvent)=>{if(event.key==='Tab'){reveal();return}if((event.target as Element|null)?.closest('input,textarea,select,[contenteditable=true]'))return;if(['ArrowUp','PageUp','Home'].includes(event.key)||event.key===' '&&event.shiftKey)intent(-1);else if(['ArrowDown','PageDown','End',' '].includes(event.key))intent(1)};
  const focus=(event:FocusEvent)=>{if((event.target as Element|null)?.closest('.workspace>header,.chat-top,.workspace>.integration-binding-picker'))reveal()};
  const resize=()=>{if(!media.matches)reveal();lastTop=container.scrollTop;lastHeight=container.scrollHeight;lastViewport=container.clientHeight;armedUntil=0};
  container.addEventListener('scroll',scroll,{passive:true});container.addEventListener('wheel',wheel,{passive:true});container.addEventListener('touchstart',start,{passive:true});container.addEventListener('touchmove',move,{passive:true});document.addEventListener('keydown',key,true);document.addEventListener('focusin',focus);media.addEventListener('change',resize);
  return()=>{container.removeEventListener('scroll',scroll);container.removeEventListener('wheel',wheel);container.removeEventListener('touchstart',start);container.removeEventListener('touchmove',move);document.removeEventListener('keydown',key,true);document.removeEventListener('focusin',focus);media.removeEventListener('change',resize)};
 },[container,conversationKey,enabled,reveal]);
 return {hidden:enabled&&hidden,reveal,restoreNavigation};
}
