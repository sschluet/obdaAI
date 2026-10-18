import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {Check, Mail, X} from 'lucide-react';
import type {IntegrationAPI} from './IntegrationRegistryPanel';

export type ProtonBridgeSetupView = {
  available: boolean; integration_id: string | null; name: string; username: string;
  revision: number; connected: boolean; message: string; enable_reads?: boolean;
};

export function ProtonBridgeSetupPanel({api, onSaved, onStateChange, onClose, openRequest = 0, refreshRequest = 0}: {
  api: IntegrationAPI; onSaved: () => void; onStateChange: (state: ProtonBridgeSetupView) => void;
  onClose?: () => void; openRequest?: number; refreshRequest?: number;
}) {
  const [setup, setSetup] = useState<ProtonBridgeSetupView | null>(null);
  const [name, setName] = useState('Proton Mail · Postfach');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [reads, setReads] = useState(true);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const lock = useRef(false), isOpen = useRef(false), currentSetup = useRef(setup);
  const dialog = useRef<HTMLDivElement>(null), credentials = useRef<HTMLFormElement>(null);
  const closeRef = useRef(() => {});
  currentSetup.current = setup; isOpen.current = open;
  function populate(state: ProtonBridgeSetupView) {
    setName(state.name || 'Proton Mail · Postfach'); setUsername(state.username || '');
    setReads(state.username ? (state.enable_reads ?? false) : true); setPassword('');
  }
  useEffect(() => {
    let active = true;
    void api('/integrations/proton-bridge-setup').then((state: ProtonBridgeSetupView) => {
      if (!active) return;
      const firstLoad = !currentSetup.current;
      setSetup(state); onStateChange(state);
      if (!isOpen.current || firstLoad) {
        populate(state);
        if (isOpen.current && firstLoad) setStep(state.username ? 2 : 1);
      }
    }).catch(() => {if (active && isOpen.current) setError('Die Bridge-Einrichtung konnte nicht geladen werden. Schließe den Dialog und versuche es erneut.');});
    return () => {active = false;};
  }, [api, onStateChange, refreshRequest, openRequest]);
  useEffect(() => {
    if (!openRequest) return;
    const state = currentSetup.current;
    if (state) populate(state);
    setPassword(''); setError(''); setNotice(''); setStep(state?.username ? 2 : 1); setOpen(true);
  }, [openRequest]);
  function close() {
    if (lock.current) return;
    setOpen(false); setPassword(''); setError(''); setNotice(''); onClose?.();
  }
  closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const shell = document.querySelector<HTMLElement>('.shell'), wasInert = shell?.inert;
    if (shell) shell.inert = true;
    const focus = requestAnimationFrame(() => dialog.current?.focus());
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {event.preventDefault(); closeRef.current();}
      if (event.key !== 'Tab') return;
      const controls = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),summary,a[href],[tabindex="0"]') || []).filter(item => item.getClientRects().length > 0 && !item.closest('fieldset:disabled'));
      const first = controls[0], last = controls.at(-1);
      if (!first) {event.preventDefault(); dialog.current?.focus();}
      else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current || !dialog.current?.contains(document.activeElement))) {event.preventDefault(); last?.focus();}
      else if (!event.shiftKey && (document.activeElement === last || !dialog.current?.contains(document.activeElement))) {event.preventDefault(); first.focus();}
    };
    document.addEventListener('keydown', key);
    return () => {
      cancelAnimationFrame(focus); document.removeEventListener('keydown', key);
      if (shell) shell.inert = !!wasInert;
      requestAnimationFrame(() => {
        if (previous?.isConnected && previous !== document.body) previous.focus();
        else document.querySelector<HTMLButtonElement>('.integration-registry > .registry-heading button')?.focus();
      });
    };
  }, [open]);
  useEffect(() => {if (open) requestAnimationFrame(() => dialog.current?.querySelector<HTMLElement>('[data-step-heading]')?.focus());}, [open, step]);
  async function save() {
    if (!setup || lock.current || notice) return;
    if (!name.trim() || !username.trim() || (!password && (!setup.username || setup.username !== username.trim()))) {
      setStep(2); setError('Ergänze die Bridge-Zugangsdaten, bevor du die Verbindung prüfst.'); return;
    }
    lock.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const state: ProtonBridgeSetupView = await api('/integrations/proton-bridge-setup', 'POST', {
        name: name.trim(), username: username.trim(), password: password || null,
        expected_revision: setup.revision, request_id: crypto.randomUUID(), enable_reads: reads,
      });
      setSetup(state); onStateChange(state); populate(state);
      setNotice('Postfachverbindung gespeichert und geprüft.'); onSaved();
    } catch (e) {
      setPassword(''); setError((e as Error).message); setStep(2);
      // A failed or interrupted setup needs a fresh revision and a new explicit attempt.
      try {
        const state: ProtonBridgeSetupView = await api('/integrations/proton-bridge-setup');
        setSetup(state); onStateChange(state); onSaved();
      } catch { /* Another explicit attempt remains subject to server revision checks. */ }
    } finally {lock.current = false; setBusy(false);}
  }
  if (!open) return null;
  return createPortal(<div className="modal registry-overlay proton-wizard-overlay">
    <div className="registry-dialog proton-wizard" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="proton-wizard-title" tabIndex={-1}>
      <div className="registry-heading"><div><h2 id="proton-wizard-title"><Mail size={21}/>Proton Mail einrichten</h2><p>Dein Postfach in Chat, Aufgaben und Projekten verwenden.</p></div><button type="button" aria-label="Einrichtung schließen" disabled={busy} onClick={close}><X size={19}/></button></div>
      {!setup ? error ? <p role="alert" className="error">{error}</p> : <p role="status">Bridge-Einrichtung wird geladen …</p> : !setup.available ? <div className="proton-wizard-unavailable"><h3 data-step-heading tabIndex={-1}>Bridge auf dem Server vorbereiten</h3><p>Die lokale Proton Bridge ist für diesen Arbeitsraum noch nicht eingerichtet. Bitte den Betreiber die Servereinrichtung abschließen lassen; anschließend kannst du hier dein Postfach verbinden.</p><a href="https://proton.me/support/bridge-cli-guide" target="_blank" rel="noopener noreferrer">Offizielle Proton-Anleitung öffnen</a><div className="dialog-actions"><button type="button" onClick={close}>Schließen</button></div></div> : <>
        <ol className="proton-wizard-steps" aria-label="Einrichtungsschritte">{['Vorbereiten', 'Zugangsdaten', 'Prüfen und verbinden'].map((title, index) => <li key={title} aria-current={step === index + 1 ? 'step' : undefined}><span>{index + 1}</span>{title}</li>)}</ol>
        {error && <p role="alert" className="error">{error}</p>}
        {step === 1 && <section className="proton-wizard-step">
          <h3 data-step-heading tabIndex={-1}>1. Vorbereiten</h3>
          <p>Du benötigst einen kostenpflichtigen Proton-Mail-Tarif und die Zugangsdaten der Proton Bridge auf diesem Server.</p>
          <p>Die Bridge ist serverseitig vorbereitet. Dein Proton-Konto muss dort bereits angemeldet sein. Halte den Bridge-Benutzernamen und das eigene Bridge-Passwort für Mailprogramme bereit.</p>
          <details className="proton-wizard-help"><summary>Noch keine Bridge-Zugangsdaten?</summary><ol><li>Öffne gemeinsam mit dem Betreiber die Proton Bridge auf diesem Server über dessen privaten Serverzugang.</li><li>Melde dein Proton-Konto direkt in Bridge an und bestätige dort gegebenenfalls 2FA. Diese Kontoanmeldung ist derzeit außerhalb von obdaAI erforderlich.</li><li>Lass dir in Bridge die Zugangsdaten für Mailprogramme anzeigen und übernimm Benutzername und Bridge-Passwort im nächsten Schritt.</li></ol><p><a href="https://proton.me/support/bridge-cli-guide" target="_blank" rel="noopener noreferrer">Offizielle Anleitung für die Bridge auf Linux öffnen</a></p></details>
          <div className="dialog-actions"><button type="button" onClick={close}>Abbrechen</button><button type="button" className="primary" onClick={() => setStep(2)}>Ich habe die Bridge-Zugangsdaten</button></div>
        </section>}
        {step === 2 && <form className="proton-wizard-step" ref={credentials} onSubmit={event => {event.preventDefault(); setError(''); setStep(3);}}>
          <h3 data-step-heading tabIndex={-1}>2. Zugangsdaten</h3>
          <p>Verwende das von Bridge erzeugte Passwort für Mailprogramme. Die Anmeldung an deinem Proton-Konto und 2FA erfolgen direkt in Bridge.</p>
          <fieldset disabled={busy}>
            <label>Name der Verbindung<input required maxLength={80} value={name} onChange={e => setName(e.target.value)}/></label>
            <div className="registry-fields"><label>Bridge-Benutzername<input required maxLength={254} autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} placeholder="Deine Proton-Mailadresse"/></label><label>Bridge-Passwort<input type="password" autoComplete="new-password" required={!setup.username || setup.username !== username.trim()} maxLength={4096} value={password} onChange={e => setPassword(e.target.value)} placeholder={setup.username && setup.username === username.trim() ? 'Leer lassen: beibehalten' : 'Passwort aus Proton Bridge'}/></label></div>
            <p className="hint">Ein vorhandenes Bridge-Passwort bleibt bei unverändertem Benutzernamen erhalten, wenn du das Feld leer lässt.</p>
            <label className="registry-checkbox"><input type="checkbox" checked={reads} onChange={e => setReads(e.target.checked)}/>Lokales Lesen und Suchen über Chat, Aufgaben und Projekte erlauben</label>
            <p className="hint">Lesen umfasst Ordner, Nachrichten, Suche, Threads und Anhanginformationen. Versand und Änderungen am Postfach bleiben gesperrt.</p>
            <div className="dialog-actions"><button type="button" onClick={() => setStep(1)}>Zurück</button><button type="submit" className="primary">Weiter zur Prüfung</button></div>
          </fieldset>
        </form>}
        {step === 3 && <section className="proton-wizard-step">
          <h3 data-step-heading tabIndex={-1}>{notice ? 'Postfach eingerichtet' : '3. Prüfen und verbinden'}</h3>
          {notice ? <><p role="status" className="proton-wizard-success"><Check size={20}/>{notice}</p><p>{reads ? 'Du kannst dieses Postfach jetzt in Chat, Aufgaben oder Projekten auswählen und lokal lesen lassen.' : 'Der Zugang wurde gespeichert. Aktiviere den lokalen Lesezugriff bei Bedarf über die Einrichtung.'}</p></> : <><p>Prüfe deine Auswahl. Erst mit dem nächsten Klick wird der Bridge-Zugang getestet und gespeichert.</p><dl className="proton-wizard-summary"><dt>Verbindung</dt><dd>{name}</dd><dt>Bridge-Benutzername</dt><dd>{username}</dd><dt>Bridge-Passwort</dt><dd>{password ? 'Neu eingegeben · verdeckt' : 'Gespeicherten Zugang beibehalten'}</dd><dt>Lokaler Lesezugriff</dt><dd>{reads ? 'Erlaubt für Chat, Aufgaben und Projekte' : 'Ausgeschaltet'}</dd></dl><p className="hint">Die Prüfung versendet keine E-Mail und verändert keine Nachrichten.</p></>}
          <div className="dialog-actions">{notice ? <button type="button" className="primary" onClick={close}>Fertig</button> : <><button type="button" disabled={busy} onClick={() => setStep(2)}>Zurück</button><button type="button" className="primary" disabled={busy} onClick={() => void save()}>{busy ? 'Postfach wird geprüft …' : 'Verbindung prüfen und speichern'}</button></>}</div>
        </section>}
      </>}
    </div>
  </div>, document.body);
}
