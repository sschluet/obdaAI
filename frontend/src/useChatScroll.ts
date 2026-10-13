import {useCallback,useLayoutEffect,useRef,useState} from 'react';

// Follow is a user choice, not a consequence of each new streaming token.
export function useChatScroll(conversationKey:string,update:unknown){
 const [container,setContainer]=useState<HTMLElement|null>(null);
 const [content,setContent]=useState<HTMLDivElement|null>(null);
 const [following,setFollowing]=useState(true);
 const follow=useRef(true),frame=useRef<number|null>(null),programmaticTop=useRef<number|null>(null);
 const changeFollow=useCallback((value:boolean)=>{follow.current=value;setFollowing(value);if(!value&&frame.current!==null){cancelAnimationFrame(frame.current);frame.current=null}},[]);
 const schedule=useCallback(()=>{
  if(!container||!follow.current||frame.current!==null)return;
  frame.current=requestAnimationFrame(()=>{frame.current=null;if(follow.current){container.scrollTop=container.scrollHeight;programmaticTop.current=container.scrollTop}});
 },[container]);
 const resume=useCallback(()=>{changeFollow(true);schedule()},[changeFollow,schedule]);
 const jumpToEnd=useCallback(()=>{resume();container?.focus({preventScroll:true})},[resume,container]);

 useLayoutEffect(()=>{
  if(!container)return;
  changeFollow(true);
  programmaticTop.current=null;
  let lastTop=container.scrollTop,lastHeight=container.scrollHeight,lastViewport=container.clientHeight,touchY:number|null=null;
  const atEnd=()=>container.scrollHeight-container.clientHeight-container.scrollTop<=2;
  const scroll=()=>{
   const top=container.scrollTop,height=container.scrollHeight,viewport=container.clientHeight;
   // A layout clamp can reduce scrollTop; only movement in unchanged geometry
   // signals a scrollbar/user scroll. Wheel, touch and keys detach earlier.
   const ownScroll=programmaticTop.current!==null&&Math.abs(top-programmaticTop.current)<=1;
   programmaticTop.current=null;
   if(!ownScroll&&top<lastTop-1&&height===lastHeight&&viewport===lastViewport)changeFollow(false);
   else if(!ownScroll&&!follow.current&&top>lastTop+1&&atEnd())changeFollow(true);
   lastTop=top;lastHeight=height;lastViewport=viewport;
  };
  const wheel=(event:WheelEvent)=>{
   const target=event.target as Element|null;
   // Scrolling a code block or table should not change the conversation's mode.
   for(let node=target;node&&node!==container;node=node.parentElement){
    const canConsume=event.deltaY<0?node.scrollTop>0:node.scrollHeight-node.clientHeight-node.scrollTop>1;
    if(canConsume&&node.scrollHeight>node.clientHeight+1&&['auto','scroll'].includes(getComputedStyle(node).overflowY))return;
   }
   if(event.deltaY<0)changeFollow(false);
   else if(event.deltaY>0&&atEnd())resume();
  };
  const touchStart=(event:TouchEvent)=>{touchY=event.touches[0]?.clientY??null};
  const touchMove=(event:TouchEvent)=>{const next=event.touches[0]?.clientY;if(next!==undefined&&touchY!==null&&next>touchY+1)changeFollow(false);if(next!==undefined)touchY=next};
  const pointer=(event:PointerEvent)=>{if(event.target===container&&event.clientX>=container.getBoundingClientRect().right-20)changeFollow(false)};
  const key=(event:KeyboardEvent)=>{
   if((event.target as Element|null)?.closest('input,textarea,select,[contenteditable="true"]'))return;
   if(['ArrowUp','PageUp','Home'].includes(event.key)||(event.key===' '&&event.shiftKey))changeFollow(false);
  };
  const observer=new ResizeObserver(()=>schedule());
  observer.observe(container);if(content)observer.observe(content);
  container.addEventListener('scroll',scroll,{passive:true});
  container.addEventListener('wheel',wheel,{passive:true});
  container.addEventListener('touchstart',touchStart,{passive:true});
  container.addEventListener('touchmove',touchMove,{passive:true});
  container.addEventListener('pointerdown',pointer,{passive:true});
  container.addEventListener('keydown',key);
  schedule();
  return()=>{
   observer.disconnect();container.removeEventListener('scroll',scroll);container.removeEventListener('wheel',wheel);
   container.removeEventListener('touchstart',touchStart);container.removeEventListener('touchmove',touchMove);container.removeEventListener('keydown',key);
   container.removeEventListener('pointerdown',pointer);
   if(frame.current!==null){cancelAnimationFrame(frame.current);frame.current=null}
  };
 },[container,content,conversationKey,changeFollow,resume,schedule]);
 useLayoutEffect(()=>schedule(),[update,schedule]);
 return {containerRef:setContainer,contentRef:setContent,following,resume,jumpToEnd};
}
