import {useEffect, useRef, useState} from 'react';
import {AgentPolicyEditor} from './AgentPolicyEditor';
import {IntegrationBindingPicker} from './IntegrationBindingPicker';
import type {IntegrationAPI, IntegrationRow} from './IntegrationRegistryPanel';
import './agent.css';

export type AgentJob = {id: string; status: string; goal: string; summary: string; cancel_requested: boolean;
  steps: {sequence: number; kind: string; status: string; sha256: string; document: any; result: any}[]};
const stepNames:Record<string,string>={prepared:'vorbereitet',dispatching:'wird ausgeführt',verifying:'Sollzustand wird geprüft',succeeded:'abgeschlossen',uncertain:'Wirkung unklar',failed:'fehlgeschlagen',unavailable:'nicht verfügbar'};
const kindNames:Record<string,string>={input:'Deine Angabe',research:'Öffentliche Recherche',effect:'Änderung',read:'Prüfung',verification:'Sollzustand prüfen',error:'Fehler',feedback:'Modellentscheidung korrigieren'};
const active = ['queued', 'running', 'awaiting_approval', 'awaiting_input'];
const names: Record<string, string> = {queued: 'Eingeplant', running: 'In Arbeit', awaiting_approval: 'Freigabe erforderlich', awaiting_input: 'Rückfrage', succeeded: 'Ausführung und Prüfschritte abgeschlossen', observed: 'Nur lesende Schritte abgeschlossen', failed: 'Angehalten', uncertain: 'Wirkung unklar', unverified: 'Wirkung nicht vollständig belegt', cancelled: 'Abgebrochen'};

export function AgentRunsPanel({api, conversationId, taskId, setup = false, onState, onChanged}: {
  api: IntegrationAPI; conversationId?: string; taskId?: string; setup?: boolean;
  onState?: (job: AgentJob | null) => void; onChanged?: () => void;
}) {
  const [jobs, setJobs] = useState<AgentJob[]>([]), [error, setError] = useState('');
  const [rows, setRows] = useState<IntegrationRow[]>([]), [editing, setEditing] = useState<IntegrationRow | null>(null);
  const [pause, setPause] = useState<any>(null), [busy, setBusy] = useState(false);
  const [receipts, setReceipts] = useState<Record<string, unknown>>({});
  const callbacks = useRef({onState, onChanged}); callbacks.current = {onState, onChanged};
  const signature = useRef('');
  const filter = taskId ? 'task_id=' + taskId : 'conversation_id=' + conversationId;
  useEffect(() => {
    if (!conversationId && !taskId) return;
    let alive = true, timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const next: AgentJob[] = await api('/agent-runs?' + filter);
        if (!alive) return;
        setJobs(next); setError('');
        callbacks.current.onState?.(next[0] || null);
        const value = JSON.stringify(next.map(j => [j.id, j.status, j.steps.map(s => [s.sequence, s.status]), j.cancel_requested]));
        if (signature.current && signature.current !== value) callbacks.current.onChanged?.();
        signature.current = value;
      } catch (e) {if (alive) setError((e as Error).message);}
      if (alive) timer = setTimeout(() => void load(), 2000);
    }
    void load();
    return () => {alive = false; clearTimeout(timer); callbacks.current.onState?.(null);};
  }, [api, filter, conversationId, taskId]);
  useEffect(() => {
    if (!setup) return;
    let alive = true;
    Promise.all([api('/integrations'), api('/action-policy')]).then(([registry, policy]) => {
      if (alive) {setRows(registry.integrations); setPause(policy);}
    }).catch(e => {if (alive) setError(e.message);});
    return () => {alive = false;};
  }, [api, setup]);
  async function perform(path: string, body = {}) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const job = await api(path, 'POST', body);
      setJobs(previous => previous.some(item => item.id === job.id) ? previous.map(item => item.id === job.id ? job : item) : [job, ...previous]);
      callbacks.current.onState?.(job); callbacks.current.onChanged?.();
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  if (!setup && !jobs.length && !error) return null;
  return <section className="agent-runs" aria-label="Systemsteuerung">
    <h3>Systemsteuerung</h3>
    {error && <p className="error" role="alert">{error}</p>}
    {setup && <details><summary>Zugriff und Agentenregeln einrichten</summary>
      {conversationId && <IntegrationBindingPicker api={api} scope="conversation" ownerId={conversationId}/>}
      <p>Die lokale KI kann im Chat recherchieren und Werkzeuge mehrstufig ausführen. Zielsysteme benötigen eine aktive Verbindung, eigene Agentenregeln und für Änderungen zusätzlich Profil-Schreibrechte.</p>
      {rows.map(row => <button type="button" key={row.id} onClick={() => setEditing(row)}>Agentenregeln · {row.name}</button>)}
      {pause && <p>Globale Schreibpause: {pause.paused ? 'aktiv' : 'aufgehoben'} <button type="button" disabled={busy} onClick={async () => {
        setBusy(true); setError('');
        try {setPause(await api('/action-policy', 'PATCH', {paused: !pause.paused, expected_revision: pause.revision}));}
        catch (e) {setError((e as Error).message);} finally {setBusy(false);}
      }}>{pause.paused ? 'Schreibpause aufheben' : 'Schreibaktionen pausieren'}</button></p>}
      {editing && <AgentPolicyEditor api={api} integration={editing} onClose={() => setEditing(null)}/>}
    </details>}
    {jobs.slice(0, 5).map(job => <details key={job.id} open={active.includes(job.status)}>
      <summary>{names[job.status] || job.status} · {job.goal.slice(0, 100)}</summary>
      <p role="status">{job.summary || 'Der Agent ermittelt die nächsten Schritte.'}</p>
      {job.cancel_requested && <p>Abbruch angefordert. Bereits gestartete entfernte Prozesse können weiterlaufen.</p>}
      {job.status === 'uncertain' && conversationId && <button type="button" disabled={busy} onClick={() => void perform('/conversations/' + conversationId + '/agent-runs', {
        request_id: crypto.randomUUID(), read_only: true, research_allowed: false, reconcile_job_id: job.id,
        goal: 'Prüfe ausschließlich lesend den tatsächlichen Zustand nach dem unklaren Auftrag. Keine Änderung wiederholen. Früherer Auftrag: ' + job.goal,
      })}>Tatsächlichen Zustand nur lesend prüfen</button>}
      {active.includes(job.status) && <button type="button" disabled={busy || job.cancel_requested} onClick={() => void perform('/agent-runs/' + job.id + '/cancel')}>Agentenlauf abbrechen</button>}
      {job.steps.filter(s => s.kind !== 'model').map((step,index) => <article key={step.sequence}>
        <p>Schritt {index+1}: {step.document.message&&step.document.message!==step.kind ? step.document.message : kindNames[step.kind]||step.kind} · {stepNames[step.status]||step.status}</p>
        {step.kind === 'effect' && step.status === 'prepared' && job.status === 'awaiting_approval' && <>
          <pre>{JSON.stringify(step.document, null, 2)}</pre>
          <button type="button" className="primary" disabled={busy} onClick={() => void perform('/agent-runs/' + job.id + '/approve', {sequence: step.sequence, sha256: step.sha256})}>Diesen Schritt freigeben und fortsetzen</button>
        </>}
        <details onToggle={e => {
          const key = job.id + ':' + step.sequence + ':' + job.status + ':' + job.steps.length;
          if (e.currentTarget.open && !receipts[key]) void api('/agent-runs/' + job.id + '/steps/' + step.sequence).then(value => setReceipts(previous => ({...previous, [key]: value}))).catch(e => setError(e.message));
        }}><summary>Aufruf und Beleg</summary><pre>{JSON.stringify(receipts[job.id + ':' + step.sequence + ':' + job.status + ':' + job.steps.length] || 'Beleg laden …', null, 2)}</pre></details>
      </article>)}
      {job.status === 'awaiting_input' && taskId && <form onSubmit={e => {
        e.preventDefault(); const form = e.currentTarget; const content = new FormData(form).get('reply'); const last = job.steps.at(-1);
        if (last && content) void perform('/agent-runs/' + job.id + '/reply', {sequence: last.sequence, sha256: last.sha256, content});
      }}><label>Antwort an den Agenten<textarea name="reply" required maxLength={8000}/></label><button disabled={busy}>Antworten und fortsetzen</button></form>}
    </details>)}
  </section>;
}
