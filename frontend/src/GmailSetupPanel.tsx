import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {Check, Mail, X} from 'lucide-react';
import type {IntegrationAPI} from './IntegrationRegistryPanel';
import './gmail-setup.css';

export type GmailSetupView = {
  available: boolean; integration_id: string | null; revision: number; name: string;
  client_id: string; client_secret_saved: boolean; configured: boolean;
  connected: boolean; account_email: string; redirect_uri: string; scopes: string[];
  enabled: boolean; enable_reads: boolean; network_ready: boolean; message?: string;
};
export type GmailOpenRequest = {id?: string; key: number} | null;

export function GmailSetupPanel({api, openRequest, onClose, onConfigured}: {
  api: IntegrationAPI; openRequest: GmailOpenRequest; onClose: () => void;
  onConfigured: () => void;
}) {
  const [open, setOpen] = useState(false), [step, setStep] = useState(1);
  const [setup, setSetup] = useState<GmailSetupView | null>(null);
  const [name, setName] = useState('Gmail'), [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [reads, setReads] = useState(true);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const lock = useRef(false), dialog = useRef<HTMLDivElement>(null);
  const closeRef = useRef(() => {});
  const configuredCallback = useRef(onConfigured); configuredCallback.current = onConfigured;
  function populate(view: GmailSetupView) {
    setSetup(view); setName(view.name || 'Gmail'); setClientId(view.client_id || '');
    setClientSecret(''); setReads(view.integration_id ? view.enable_reads : true);
  }
  useEffect(() => {
    if (!openRequest) {setOpen(false); setClientSecret(''); return;}
    let alive = true;
    setOpen(true); setSetup(null); setError(''); setNotice(''); setClientSecret('');
    setStep(openRequest.id ? 3 : 1);
    const query = openRequest.id ? '?integration_id=' + encodeURIComponent(openRequest.id) : '';
    void api('/integrations/gmail/setup' + query).then((view: GmailSetupView) => {
      if (!alive) return;
      populate(view);
      setStep(view.configured ? 3 : 1);
    }).catch(e => {if (alive) setError((e as Error).message);});
    return () => {alive = false;};
  }, [api, openRequest?.key]);
  function close() {
    if (lock.current) return;
    setOpen(false); setClientSecret(''); setError(''); setNotice(''); onClose();
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
      const controls = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),summary,a[href],[tabindex="0"]') || [])
        .filter(item => item.getClientRects().length > 0 && !item.closest('fieldset:disabled'));
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
  useEffect(() => {
    if (open) requestAnimationFrame(() => dialog.current?.querySelector<HTMLElement>('[data-gmail-heading]')?.focus());
  }, [open, step]);
  async function saveClient() {
    if (!setup || lock.current) return;
    lock.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const view: GmailSetupView = await api('/integrations/gmail/setup', 'POST', {
        integration_id: setup.integration_id, expected_revision: setup.integration_id ? setup.revision : null,
        request_id: crypto.randomUUID(), name: name.trim(), client_id: clientId.trim(),
        client_secret: clientSecret || null, enable_reads: reads,
      });
      populate(view); setStep(3); configuredCallback.current();
    } catch (e) {setClientSecret(''); setError((e as Error).message);}
    finally {lock.current = false; setBusy(false);}
  }
  async function authorize() {
    if (!setup?.integration_id || !setup.configured || lock.current) return;
    lock.current = true; setBusy(true); setError(''); setClientSecret('');
    try {
      const result = await api('/integrations/gmail/' + setup.integration_id + '/authorize', 'POST', {
        expected_revision: setup.revision, request_id: crypto.randomUUID(),
      });
      const url = new URL(result.authorization_url);
      if (url.origin !== 'https://accounts.google.com' || url.pathname !== '/o/oauth2/v2/auth' || url.username || url.password || url.hash) {
        throw new Error('Die Google-Anmeldeadresse wurde nicht bestätigt. Bitte erneut verbinden.');
      }
      setSetup(previous => previous ? {...previous, revision: result.revision} : previous);
      configuredCallback.current();
      window.location.assign(url.href);
    } catch (e) {setError((e as Error).message);}
    finally {lock.current = false; setBusy(false);}
  }
  async function disconnect() {
    if (!setup?.integration_id || lock.current) return;
    lock.current = true; setBusy(true); setError(''); setClientSecret('');
    try {
      const view: GmailSetupView = await api('/integrations/gmail/' + setup.integration_id + '/disconnect', 'POST', {
        expected_revision: setup.revision, revoke_google: false,
      });
      populate(view); setNotice('Der gespeicherte Postfachzugriff wurde in obdaAI getrennt.'); configuredCallback.current();
    } catch (e) {setError((e as Error).message);}
    finally {lock.current = false; setBusy(false);}
  }
  if (!open) return null;
  const canKeepSecret = setup?.client_secret_saved && clientId.trim() === setup.client_id;
  return createPortal(<div className="modal registry-overlay gmail-wizard-overlay">
    <div className="registry-dialog gmail-wizard" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="gmail-wizard-title" tabIndex={-1}>
      <div className="registry-heading"><div><h2 id="gmail-wizard-title"><Mail size={21}/>Gmail einrichten</h2><p>Dein Google-Postfach direkt über die Gmail API verbinden.</p></div><button type="button" aria-label="Gmail-Einrichtung schließen" disabled={busy} onClick={close}><X size={19}/></button></div>
      {!setup ? error ? <p role="alert" className="error">{error}</p> : <p role="status">Gmail-Einrichtung wird geladen …</p> : !setup.available ? <section><h3 data-gmail-heading tabIndex={-1}>Servereinrichtung erforderlich</h3><p>{setup.message || 'Die Gmail-Einrichtung ist auf diesem Server noch nicht verfügbar. Bitte den Betreiber die Serverkonfiguration prüfen lassen.'}</p><button type="button" onClick={close}>Schließen</button></section> : <>
        <ol className="gmail-wizard-steps" aria-label="Gmail-Einrichtungsschritte">{['Vorbereiten', 'OAuth-Zugang', 'Mit Google verbinden'].map((title, index) => <li key={title} aria-current={step === index + 1 ? 'step' : undefined}><span>{index + 1}</span>{title}</li>)}</ol>
        {error && <p role="alert" className="error">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {step === 1 && <section className="gmail-wizard-step">
          <h3 data-gmail-heading tabIndex={-1}>1. Google Cloud vorbereiten</h3>
          <p>Für diese private Installation benötigst du einen eigenen Google-OAuth-Client. Diese Vorbereitung erfolgt einmal in deinem Google-Cloud-Projekt.</p>
          <ol><li><a href="https://console.cloud.google.com/apis/library/gmail.googleapis.com" target="_blank" rel="noopener noreferrer">Gmail API in Google Cloud aktivieren</a>.</li><li>Richte die Google Auth Platform für dein Projekt ein. Wenn du den Testmodus verwendest, füge dein eigenes Google-Konto als Testnutzer hinzu.</li><li><a href="https://console.cloud.google.com/auth/clients" target="_blank" rel="noopener noreferrer">OAuth-Client erstellen</a>: Wähle den Anwendungstyp <strong>Webanwendung</strong> und trage diese Adresse exakt als autorisierte Weiterleitungs-URI ein:</li></ol>
          <label>Autorisierte Weiterleitungs-URI<input readOnly value={setup.redirect_uri} onFocus={event => event.currentTarget.select()}/></label>
          <p>Halte anschließend die Client-ID und das Client-Secret bereit. Dein Google-Passwort wird hier nicht benötigt.</p>
          <a href="https://developers.google.com/identity/protocols/oauth2/web-server" target="_blank" rel="noopener noreferrer">Offizielle Google-Anleitung öffnen</a>
          <div className="dialog-actions"><button type="button" onClick={close}>Abbrechen</button><button type="button" className="primary" onClick={() => setStep(2)}>OAuth-Client ist vorbereitet</button></div>
        </section>}
        {step === 2 && <form className="gmail-wizard-step" onSubmit={event => {event.preventDefault(); void saveClient();}}>
          <h3 data-gmail-heading tabIndex={-1}>2. OAuth-Zugang speichern</h3>
          <p>Die Client-Zugangsdaten werden verschlüsselt gespeichert. Das Speichern allein stellt noch keine Verbindung zu Google her.</p>
          <fieldset disabled={busy}>
            <label>Name der Verbindung<input required maxLength={80} value={name} onChange={event => setName(event.target.value)}/></label>
            <label>Google-Client-ID<input required maxLength={256} autoComplete="off" value={clientId} onChange={event => setClientId(event.target.value)} placeholder="…apps.googleusercontent.com"/></label>
            <label>Google-Client-Secret<input type="password" required={!canKeepSecret} maxLength={4096} autoComplete="new-password" value={clientSecret} onChange={event => setClientSecret(event.target.value)} placeholder={canKeepSecret ? 'Leer lassen: gespeicherten Zugang behalten' : 'Client-Secret aus Google Cloud'}/></label>
            <label className="gmail-read-choice"><input type="checkbox" checked={reads} onChange={event => setReads(event.target.checked)}/>Gmail lokal lesen und durchsuchen</label>
            <p>Suchanfragen werden an Google gesendet. Abgerufene Nachrichten verarbeitet obdaAI nur lokal. Diese Auswahl erlaubt keinen Mailversand und keine Weitergabe an Cloudmodelle.</p>
            {setup.connected && <p>Wenn du diese Einstellungen speicherst, wird der bisherige Postfachzugriff getrennt. Verbinde dich anschließend erneut mit Google.</p>}
            <div className="dialog-actions"><button type="button" onClick={() => setStep(1)}>Zurück</button><button type="submit" className="primary">Zugang speichern und weiter</button></div>
          </fieldset>
        </form>}
        {step === 3 && <section className="gmail-wizard-step">
          <h3 data-gmail-heading tabIndex={-1}>{setup.connected ? 'Gmail ist verbunden' : '3. Mit Google verbinden'}</h3>
          {setup.connected ? <p role="status" className="gmail-wizard-success"><Check size={20}/>Verbunden{setup.account_email ? ' · ' + setup.account_email : ''}</p> : <p>Der OAuth-Zugang ist gespeichert. Dein Postfach ist erst nach deiner Anmeldung und Freigabe bei Google verbunden.</p>}
          <p>Google wird in diesem Browser geöffnet. Wähle dein Konto und bestätige ausschließlich den lesenden Gmail-Zugriff; danach kehrst du zu den Integrationen zurück.</p>
          <p>Diese Verbindung erlaubt keine Nachrichten zu senden, zu ändern oder zu löschen. Suchanfragen werden an Google gesendet. Abgerufene Nachrichten verarbeitet obdaAI nur lokal.</p>
          <p>{setup.enable_reads ? 'Nach erfolgreicher Google-Freigabe ist lokales Lesen und Suchen in Chat, Aufgaben und Projekten erlaubt.' : 'Der KI-Lesezugriff bleibt ausgeschaltet. Du kannst ihn über „OAuth-Zugang bearbeiten“ ausdrücklich erlauben.'}</p>
          {!setup.network_ready && <p role="status">Die Serverfreigabe für Google fehlt noch. Bitte den Betreiber die Netzwerkfreigabe prüfen lassen, bevor du dich verbindest.</p>}
          <div className="dialog-actions"><button type="button" disabled={busy} onClick={() => {setError(''); setNotice(''); setStep(2);}}>OAuth-Zugang bearbeiten</button><button type="button" className="primary" disabled={busy || !setup.configured || !setup.network_ready} onClick={() => void authorize()}>{busy ? 'Bitte warten …' : setup.connected ? 'Erneut mit Google verbinden' : 'Mit Google verbinden'}</button></div>
          {setup.connected && <details className="gmail-disconnect"><summary>Verbindung trennen</summary><p>Entfernt den gespeicherten Gmail-Zugriff aus obdaAI. Deine Nachrichten und die Freigabe in deinem Google-Konto werden dabei nicht verändert. Die Freigabe kannst du zusätzlich unter <a href="https://myaccount.google.com/connections" target="_blank" rel="noopener noreferrer">Google-Konto → Verbindungen</a> entfernen.</p><button type="button" disabled={busy} onClick={() => void disconnect()}>Postfachzugriff in obdaAI trennen</button></details>}
          <div className="dialog-actions"><button type="button" disabled={busy} onClick={close}>Schließen</button></div>
        </section>}
      </>}
    </div>
  </div>, document.body);
}
