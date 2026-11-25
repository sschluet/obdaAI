import {useLayoutEffect, useRef, useState} from 'react';
import {Check, CircleAlert, LoaderCircle, MessageCircle, Square} from 'lucide-react';
import type {AgentJob} from './AgentRunsPanel';
import type {IntegrationAPI} from './IntegrationRegistryPanel';
import {reconciliationRequest} from './agentReconciliation';
import './agent.css';

export type AgentActivityState = {
  phase: string; message: string; updated_at?: number; elapsed_seconds?: number;
  waiting_reason?: string; next_action?: string; can_cancel?: boolean;
  completed_steps?:number;total_steps?:number|null;event_key?:string;
  timeline?:{sequence:number;kind:string;status:string;message:string}[];
};
const live = new Set(['queued', 'running', 'awaiting_input', 'awaiting_approval']);
const labels: Record<string,string> = {queued:'Auftrag eingeplant',running:'Auftrag läuft',
  awaiting_input:'Deine Antwort wird benötigt',awaiting_approval:'Deine Freigabe wird benötigt',
  succeeded:'Auftrag abgeschlossen',observed:'Abfrage abgeschlossen',failed:'Auftrag angehalten',
  unverified:'Ergebnis noch nicht ausreichend belegt',uncertain:'Wirkung noch unklar',cancelled:'Auftrag abgebrochen'};

export function activityFallback(job: AgentJob): string {
  if(job.cancel_requested)return 'Abbruch angefordert. Bereits gestartete Vorgänge werden noch geprüft.';
  if(job.status==='queued')return 'Der Auftrag wartet auf seine Ausführung.';
  if(job.status==='awaiting_input')return job.summary||'Beantworte die Rückfrage unten im Chat.';
  if(job.status==='awaiting_approval')return 'Prüfe den vorgesehenen Schritt, bevor du ihn freigibst.';
  if(['succeeded','observed'].includes(job.status))return 'Die Antwort ist im Gespräch verfügbar.';
  if(job.status!=='running')return job.summary||labels[job.status]||'Der Auftrag wurde beendet.';
  const step=job.steps.at(-1);
  if(!step)return 'Der Auftrag wird vorbereitet.';
  if(step.kind==='model')return 'Die nächsten Schritte werden vorbereitet.';
  if(step.kind==='read')return step.status==='succeeded'?'Die gelesenen Informationen werden ausgewertet.':'Informationen werden aus dem angebundenen System gelesen.';
  if(step.kind==='effect')return step.status==='succeeded'?'Die Änderung wird überprüft.':'Der freigegebene Schritt wird ausgeführt.';
  if(step.kind==='verification')return 'Der tatsächliche Zustand wird überprüft.';
  if(step.kind==='research')return 'Öffentliche Informationen werden recherchiert.';
  if(step.kind==='feedback')return 'Die Planung wird anhand der bisherigen Ergebnisse korrigiert.';
  return 'Der Auftrag wird weiter bearbeitet.';
}

export function AgentActivity({job, api, latestResponse, onState, onDetails, onReply, onPrepareRetry, pendingMessage, onCancelSend, connectionError,conversationId,onNewJob,onCommandBoundary}: {
  job: AgentJob|null; api: IntegrationAPI; latestResponse: boolean;conversationId?:string;onNewJob?:(job:AgentJob)=>void;onCommandBoundary?:()=>void;
  onState:(job:AgentJob)=>void; onDetails:(id:string)=>void; onReply:()=>void;
  onPrepareRetry?:(goal:string)=>void; pendingMessage?:string;onCancelSend:()=>void;connectionError?:string;
}) {
  const [pending,setPending]=useState(false),[error,setError]=useState('');
  const generation=useRef(0),mounted=useRef(false),operationLock=useRef(false);
  const reconcileIntent=useRef<ReturnType<typeof reconciliationRequest>|null>(null);
  useLayoutEffect(()=>{mounted.current=true;generation.current++;operationLock.current=false;reconcileIntent.current=null;setPending(false);setError('');return()=>{mounted.current=false;generation.current++}},[job?.id]);
  if(!job||(!live.has(job.status)&&(!latestResponse||!!pendingMessage)))return pendingMessage?<section className="agent-activity" aria-label="Aktueller Auftrag"><div className="agent-activity-heading"><LoaderCircle size={16} className="activity-spinner" aria-hidden="true"/><strong>Deine Anfrage</strong></div><p role="status">{pendingMessage}</p><div className="agent-activity-actions"><button type="button" onClick={onCancelSend}><Square size={12}/>Abbrechen</button></div></section>:null;
  if(latestResponse&&['observed','succeeded'].includes(job.status))return null;
  const running=['queued','running'].includes(job.status),needsAnswer=job.status==='awaiting_input';
  const needsApproval=job.status==='awaiting_approval';
  const failed=['failed','unverified','uncertain'].includes(job.status);
  const activity=job.activity;
  const elapsed=typeof activity?.elapsed_seconds==='number'&&Number.isFinite(activity.elapsed_seconds)&&activity.elapsed_seconds>=0?Math.floor(activity.elapsed_seconds):null;
  const message=job.cancel_requested?activityFallback(job):activity?.message||activityFallback(job);
  const next=activity?.next_action||(needsAnswer?'Schreibe deine Antwort in das Nachrichtenfeld.':needsApproval?'Öffne den Schritt und prüfe die Freigabe.':job.status==='uncertain'?'Prüfe den tatsächlichen Zustand, bevor du eine Änderung erneut startest.':failed?'Öffne die Details, um den letzten belegten Stand zu prüfen.':'');
  async function cancel(){
    if(operationLock.current||!job)return;
    operationLock.current=true;onCommandBoundary?.();
    const version=generation.current,owner=job.id;setPending(true);setError('');
    try{const next:AgentJob=await api('/agent-runs/'+owner+'/cancel','POST',{});if(mounted.current&&generation.current===version){onCommandBoundary?.();onState(next)}}
    catch(e){if(mounted.current&&generation.current===version)setError((e as Error).message)}
    finally{if(mounted.current&&generation.current===version){operationLock.current=false;setPending(false)}}
  }
  async function reconcile(){
    if(operationLock.current||!job||!conversationId||!onNewJob)return;
    operationLock.current=true;onCommandBoundary?.();const version=generation.current;setPending(true);setError('');
    reconcileIntent.current??=reconciliationRequest(conversationId,job);
    try{const request=reconcileIntent.current,next:AgentJob=await api(request.path,'POST',request.body);if(mounted.current&&generation.current===version){onCommandBoundary?.();onNewJob(next)}}
    catch(e){if(mounted.current&&generation.current===version)setError((e as Error).message)}
    finally{if(mounted.current&&generation.current===version){operationLock.current=false;setPending(false)}}
  }
  return <section className={'agent-activity '+(failed?'needs-attention':'')} aria-label="Aktueller Auftrag" data-phase={activity?.phase||job.status}>
    <div className="agent-activity-heading">{running?<LoaderCircle size={16} className="activity-spinner" aria-hidden="true"/>:failed?<CircleAlert size={16} aria-hidden="true"/>:needsAnswer||needsApproval?<MessageCircle size={16} aria-hidden="true"/>:<Check size={16} aria-hidden="true"/>}<strong>{labels[job.status]||'Auftrag'}</strong><span className="hint">Lokal{running&&elapsed!==null?' · '+(elapsed<60?elapsed+' s':Math.floor(elapsed/60)+' min'):null}</span></div>
    <p role="status" aria-live="polite" aria-atomic="true">{connectionError?'Live-Status ist gerade nicht erreichbar. Angezeigt wird der letzte bekannte Stand.':message}</p>
    {!!activity?.completed_steps&&running&&<p className="hint">{activity.completed_steps} {activity.completed_steps===1?'Schritt abgeschlossen':'Schritte abgeschlossen'}</p>}
    {activity?.waiting_reason&&<p className="hint">{activity.waiting_reason}</p>}
    {next&&<p className="hint">{next}</p>}
    {error&&<p className="error" role="alert">{error}</p>}
    <div className="agent-activity-actions">
      {job.status==='uncertain'&&conversationId&&onNewJob&&<button type="button" className="primary" disabled={pending} onClick={()=>void reconcile()}>{pending?'Zustandsprüfung wird vorbereitet …':'Zustand prüfen'}</button>}
      {needsAnswer&&<button type="button" className="primary" onClick={onReply}>Antwort schreiben</button>}
      <button type="button" onClick={()=>onDetails(job.id)}>{needsApproval?'Schritt prüfen und freigeben':'Details anzeigen'}</button>
      {live.has(job.status)&&<button type="button" disabled={pending||job.cancel_requested||activity?.can_cancel===false} onClick={()=>void cancel()}><Square size={12}/>{job.cancel_requested?'Abbruch angefordert':'Abbrechen'}</button>}
      {onPrepareRetry&&failed&&job.status!=='uncertain'&&!job.steps.some(s=>s.kind==='effect')&&<button type="button" onClick={()=>onPrepareRetry(job.goal)}>Frage erneut vorbereiten</button>}
    </div>
  </section>;
}
