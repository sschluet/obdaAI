import {useEffect, useRef, useState} from 'react';
import {Mail} from 'lucide-react';
import type {IntegrationAPI} from './IntegrationRegistryPanel';

export type ProtonBridgeSetupView = {
  available: boolean; integration_id: string | null; name: string; username: string;
  revision: number; connected: boolean; message: string; enable_reads?: boolean;
};

export function ProtonBridgeSetupPanel({api, onSaved, onStateChange, openRequest = 0, refreshRequest = 0}: {
  api: IntegrationAPI; onSaved: () => void; onStateChange: (state: ProtonBridgeSetupView) => void;
  openRequest?: number; refreshRequest?: number;
}) {
  const [setup, setSetup] = useState<ProtonBridgeSetupView | null>(null);
  const [name, setName] = useState('Proton Mail · Postfach');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [reads, setReads] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const lock = useRef(false);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    let active = true;
    void api('/integrations/proton-bridge-setup').then((state: ProtonBridgeSetupView) => {
      if (!active) return;
      setSetup(state); onStateChange(state);
      setName(state.name || 'Proton Mail · Postfach'); setUsername(state.username || '');
      setReads(state.username ? (state.enable_reads ?? false) : true); setPassword('');
      if (!refreshRequest) setExpanded(state.available && !state.connected);
    }).catch(() => {}); // Optional server capability; generic integrations remain available.
    return () => {active = false;};
  }, [api, onStateChange, refreshRequest]);
  useEffect(() => {
    if (!openRequest) return;
    setExpanded(true); panel.current?.scrollIntoView({block: 'center', behavior: 'smooth'});
  }, [openRequest]);
  async function save() {
    if (!setup || lock.current) return;
    lock.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const state: ProtonBridgeSetupView = await api('/integrations/proton-bridge-setup', 'POST', {
        name: name.trim(), username: username.trim(), password: password || null,
        expected_revision: setup.revision, request_id: crypto.randomUUID(), enable_reads: reads,
      });
      setSetup(state); onStateChange(state); setName(state.name); setUsername(state.username);
      setPassword(''); setNotice('Postfachverbindung gespeichert und geprüft.'); onSaved();
    } catch (e) {
      setPassword(''); setError((e as Error).message);
      // A failed or interrupted setup invalidates old access. Reload its revision before retrying.
      try {
        const state: ProtonBridgeSetupView = await api('/integrations/proton-bridge-setup');
        setSetup(state); onStateChange(state); onSaved();
      } catch { /* Keep the original error; another explicit attempt must pass server revision checks. */ }
    } finally {lock.current = false; setBusy(false);}
  }
  if (!setup?.available) return null;
  return <section className="proton-bridge-setup" aria-label="Proton Mail verbinden" ref={panel}>
    <div className="registry-heading">
      <div><h3><Mail size={19}/>Proton Mail (Bridge)</h3><p>Dein Postfach in Chat, Aufgaben und Projekten verwenden.</p></div>
      <button type="button" disabled={busy} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? 'Einrichtung schließen' : 'Postfach einrichten'}</button>
    </div>
    <p className="proton-bridge-status" role="status">{setup.connected ? 'Verbunden · Zugang zuletzt erfolgreich geprüft' : 'Postfach noch nicht verbunden'}{setup.message ? ' · ' + setup.message : ''}</p>
    {expanded && <form onSubmit={e => {e.preventDefault(); void save();}}>
      <p>Verwende die Zugangsdaten der auf diesem Server eingerichteten Proton Bridge. Das Proton-Konto muss dort bereits angemeldet sein.</p>
      <fieldset disabled={busy}>
        <label>Name der Verbindung<input required maxLength={80} value={name} onChange={e => setName(e.target.value)}/></label>
        <div className="registry-fields">
          <label>Bridge-Benutzername<input required maxLength={254} autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} placeholder="Deine Proton-Mailadresse"/></label>
          <label>Bridge-Passwort<input type="password" autoComplete="new-password" required={!setup.username || setup.username !== username.trim()} maxLength={4096} value={password} onChange={e => setPassword(e.target.value)} placeholder={setup.username && setup.username === username.trim() ? 'Leer lassen: gespeicherten Zugang behalten' : 'Passwort aus Proton Bridge'}/></label>
        </div>
        <p className="hint">Bridge erzeugt ein eigenes Passwort für Mailprogramme. Verwende hier dieses Bridge-Passwort.</p>
        <label className="registry-checkbox"><input type="checkbox" checked={reads} onChange={e => setReads(e.target.checked)}/>Lokales Lesen und Suchen über Chat, Aufgaben und Projekte erlauben</label>
        <p className="hint">Die KI erhält Zugriff auf Ordner, Nachrichten, Suche, Threads und Anhanginformationen. Versand und Änderungen am Postfach bleiben gesperrt.</p>
        {error && <p role="alert" className="error">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        <div className="dialog-actions"><button className="primary" disabled={busy}>{busy ? 'Postfach wird geprüft …' : 'Verbindung prüfen und speichern'}</button></div>
      </fieldset>
    </form>}
  </section>;
}
