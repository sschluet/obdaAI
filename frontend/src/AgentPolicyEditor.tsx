import {useEffect, useState} from 'react';
import type {IntegrationAPI, IntegrationRow} from './IntegrationRegistryPanel';

type MCPReadCandidate = {name: string; description: string; schema_sha256: string};

export function AgentPolicyEditor({api, integration, onClose}: {
  api: IntegrationAPI; integration: IntegrationRow; onClose: () => void;
}) {
  const [policy, setPolicy] = useState<any>(null);
  const [rules, setRules] = useState<any>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [writes, setWrites] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  useEffect(() => {
    let alive = true;
    setPolicy(null); setRules(null); setError(''); setAdvanced(false);
    api('/integrations/' + integration.id + '/agent-policy').then(p => {
      if (alive) {setPolicy(p); setRules(p.rules); setWrites(p.writes_enabled);}
    }).catch(e => {if (alive) setError(e.message);});
    return () => {alive = false;};
  }, [api, integration.id]);
  const change = (key: string, value: unknown) => setRules({...rules, [key]: value});
  const readCandidates: MCPReadCandidate[] = policy?.mcp_read_candidates ?? [];
  const readTools: Record<string, string> = rules?.mcp_read_tools ?? {};
  const staleReadTools = Object.keys(readTools).filter(name => !readCandidates.some(tool => tool.name === name && tool.schema_sha256 === readTools[name]));
  function allowReadTool(name: string, schema: string, allowed: boolean) {
    const next = {...readTools};
    if (allowed) next[name] = schema;
    else delete next[name];
    change('mcp_read_tools', next);
  }
  const access = !rules?.enabled ? 'off' : writes ? 'approval' : 'read';
  const supportsHTTP = ['home_assistant', 'paperless', 'unifi'].includes(integration.kind);
  const httpRead = supportsHTTP && rules?.http_prefixes.length > 0 && rules.http_methods.includes('GET');
  const haRead = integration.kind === 'home_assistant' && ['backup/info', 'supervisor/api'].some(command =>
    rules?.ha_websocket_prefixes.some((prefix: string) => prefix.endsWith('/') ? command.startsWith(prefix) : command === prefix));
  const hasReads = integration.kind === 'ssh' || httpRead || haRead ||
    integration.kind === 'mcp' && Object.keys(readTools).some(name => !staleReadTools.includes(name));
  const hasChanges = rules && rules.max_effects > 0 && (
    supportsHTTP && rules.http_prefixes.length > 0 && rules.http_methods.some((method: string) => method !== 'GET') ||
    integration.kind === 'home_assistant' && rules.ha_websocket_prefixes.length > 0 ||
    integration.kind === 'ssh' && rules.shell || integration.kind === 'mcp' && rules.mcp ||
    integration.kind === 'smtp' && rules.mail_recipients.length > 0);
  function chooseAccess(value: 'off' | 'read' | 'approval') {
    setRules({...rules, enabled: value !== 'off', autonomous: false});
    setWrites(value === 'approval');
  }
  async function save() {
    setBusy(true); setError('');
    try {
      let profileRevision = policy.profile_revision;
      if (writes !== policy.writes_enabled) {
        const result = await api('/integrations/' + integration.id + '/write-control', 'PATCH', {expected_revision: profileRevision, writes_enabled: writes});
        profileRevision = result.revision;
        setPolicy((previous: any) => ({...previous, profile_revision: profileRevision, writes_enabled: writes, current: false}));
      }
      await api('/integrations/' + integration.id + '/agent-policy', 'PUT', {
        expected_revision: policy.revision, expected_profile_revision: profileRevision, rules,
      });
      onClose();
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <section className="setting-card agent-policy" aria-label={'KI-Zugriff für ' + integration.name}>
    <h3>KI-Zugriff · {integration.name}</h3>
    <p>Lege fest, wie die KI diese Verbindung in Chat, Aufgaben und Projekten verwenden darf. Änderungen gelten nach dem Speichern.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {rules && <fieldset disabled={busy}>
      {!policy.current && policy.revision > 0 && <p>Das Profil wurde geändert. Die Regeln müssen erneut freigegeben werden.</p>}
      <fieldset className="agent-access-options" aria-label="Zugriff auswählen">
        <legend>Was darf die KI hier tun?</legend>
        <div className="agent-access-choice"><label><input type="radio" name={'ki-access-' + integration.id} checked={access === 'off'} onChange={() => chooseAccess('off')}/>Kein KI-Zugriff</label>
        <p>Diese Verbindung steht der KI nicht zur Verfügung.</p></div>
        <div className="agent-access-choice"><label><input type="radio" name={'ki-access-' + integration.id} checked={access === 'read'} onChange={() => chooseAccess('read')}/>Nur lesen</label>
        <p>Die KI darf die ausdrücklich freigegebenen Informationen abrufen. Änderungen bleiben gesperrt.</p></div>
        <div className="agent-access-choice"><label><input type="radio" name={'ki-access-' + integration.id} checked={access === 'approval'} onChange={() => chooseAccess('approval')}/>Änderungen erlauben</label>
        <p>{rules.enabled && writes && rules.autonomous ? 'Die KI führt bereits freigegebene Änderungen selbstständig aus.' : 'Du bestätigst jede Änderung vor der Ausführung.'}</p></div>
      </fieldset>
      {!integration.enabled && <p>Diese Verbindung ist deaktiviert. Aktiviere sie in der Integrationsübersicht, bevor die KI sie verwenden kann.</p>}
      {rules.enabled && writes && rules.autonomous && <p role="status">Selbstständige Ausführung ist bereits aktiv. Du kannst sie unter „Erweiterte Berechtigungen“ ausschalten.</p>}
      {rules.enabled && !hasReads && !writes && <p>Noch keine Aktionen freigegeben. Ein erfolgreicher Verbindungstest allein erlaubt noch keinen Zugriff auf Inhalte. <button type="button" onClick={() => setAdvanced(true)}>Berechtigungen einrichten</button></p>}
      {rules.enabled && writes && !hasChanges && <p>Noch keine Änderungen freigegeben. Richte die erlaubten Aktionen und ihre Grenzen ein. <button type="button" onClick={() => setAdvanced(true)}>Berechtigungen einrichten</button></p>}
      <p>Für alle Optionen gelten die unter „Erweiterte Berechtigungen“ festgelegten Aktionen.</p>
      <details open={advanced} onToggle={e => setAdvanced(e.currentTarget.open)}>
        <summary>Erweiterte Berechtigungen</summary>
        <p>Ziel: {integration.config.url}{integration.kind === 'ssh' ? ' · Konto: ' + integration.config.username : ''}</p>
        <label><input type="checkbox" checked={rules.autonomous} disabled={!rules.enabled || !writes} onChange={e => change('autonomous', e.target.checked)}/>Freigegebene Änderungen ohne einzelne Rückfrage ausführen</label>
        <p>Dies gilt nur für die unten erlaubten Aktionen und Laufgrenzen. Die globale Schreibpause bleibt wirksam.</p>
        <label><input type="checkbox" checked={rules.private_data_to_target} onChange={e => change('private_data_to_target', e.target.checked)}/>Private Informationen auch an die öffentliche Adresse dieses Zielsystems übertragen</label>
        <p>Diese Freigabe gilt für das angegebene Systemkonto. Sie erlaubt keine Weitergabe an Cloudmodelle oder öffentliche Suchdienste.</p>
      {['home_assistant', 'paperless', 'unifi'].includes(integration.kind) && <>
        <label><input type="checkbox" checked={rules.file_upload} onChange={e => change('file_upload', e.target.checked)}/>Originaldateien aus dem gebundenen Auftragskontext übertragen</label>
        <label>Erlaubte API-Pfade (je Zeile ein Präfix mit abschließendem /)
          <textarea rows={3} value={rules.http_prefixes.join('\n')} placeholder={integration.kind === 'unifi' ? '/v1/' : '/api/'} onChange={e => change('http_prefixes', e.target.value.split('\n').filter(Boolean))}/>
        </label>
        <div>{['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map(method => <label key={method}>
          <input type="checkbox" checked={rules.http_methods.includes(method)} onChange={e => change('http_methods', e.target.checked ? [...rules.http_methods, method] : rules.http_methods.filter((m: string) => m !== method))}/>{method}
        </label>)}</div>
      </>}
      {integration.kind === 'home_assistant' && <label>Erlaubte WebSocket-Befehle oder Präfixe mit / (je Zeile)<textarea rows={3} placeholder={'config/\ninput_boolean/'} value={rules.ha_websocket_prefixes.join('\n')} onChange={e => change('ha_websocket_prefixes', e.target.value.split('\n').filter(Boolean))}/></label>}
      {integration.kind === 'ssh' && <>
        <label><input type="checkbox" checked={rules.home_assistant_host} onChange={e => change('home_assistant_host', e.target.checked)}/>Dieses Konto verwaltet einen Home-Assistant-Host</label>
        <label><input type="checkbox" checked={rules.shell} onChange={e => change('shell', e.target.checked)}/>Selbst erzeugte Shellbefehle und Konfigurationsskripte erlauben</label>
        <p>Ausführung mit den tatsächlichen Rechten dieses entfernten Kontos, einschließlich dessen Netzwerk- und sudo-Rechten. Ein Arbeitsordner ist keine Sandbox.</p>
        <label>Lesbare Dateiwurzeln (je Zeile ein absoluter Pfad)<textarea rows={3} value={rules.file_read_roots.join('\n')} onChange={e => change('file_read_roots', e.target.value.split('\n').filter(Boolean))}/></label>
      </>}
      {(integration.kind === 'home_assistant' || rules.home_assistant_host) && <label><input type="checkbox" checked={rules.production_ha_approved} onChange={e => change('production_ha_approved', e.target.checked)}/>Direkte Änderungen an dieser HA-Instanz erlauben, auch ohne abgeschlossenen Wiederherstellungstest. Dies bestätigt keinen geprüften Restore.</label>}
      {integration.kind === 'mcp' && <>
        <fieldset aria-label="Lesende MCP-Werkzeuge freigeben">
          <legend>Einzelne MCP-Werkzeuge als lesend freigeben</legend>
          <p>Markiere ein Werkzeug erst, nachdem du geprüft hast, dass es ausschließlich liest. Deine Auswahl erlaubt seine Ausführung ohne Schreibfreigabe. Werkzeugbeschreibungen stammen vom angebundenen Server und sind keine geprüfte Einstufung.</p>
          {readCandidates.length ? readCandidates.map(tool => <div key={tool.name}>
            <label><input type="checkbox" checked={readTools[tool.name] === tool.schema_sha256} onChange={e => allowReadTool(tool.name, tool.schema_sha256, e.target.checked)}/>{tool.name}</label>
            {tool.description && <p>{tool.description}</p>}
          </div>) : <p>Prüfe zuerst den Zugang, um den aktuellen Werkzeugkatalog zu laden.</p>}
          {!!staleReadTools.length && <div>
            <p>Diese Freigaben passen nicht zum aktuellen Katalog. Prüfe den Zugang und gib geänderte Werkzeuge nach erneuter Prüfung frei.</p>
            {staleReadTools.map(name => <label key={name}><input type="checkbox" checked onChange={() => allowReadTool(name, '', false)}/>{name} · bisherige Freigabe entfernen</label>)}
          </div>}
          <p>Die Auswahl gilt nur für die geprüfte Werkzeugversion. Neue oder geänderte Werkzeuge erhalten keine automatische Freigabe.</p>
        </fieldset>
        <label><input type="checkbox" checked={rules.mcp} onChange={e => change('mcp', e.target.checked)}/>Alle aktuellen MCP-Werkzeuge dieses Serverkontos einschließlich Änderungen zulassen</label>
      </>}
      {integration.kind === 'smtp' && <label>Erlaubte E-Mail-Empfänger (je Zeile eine Adresse)<textarea rows={3} value={rules.mail_recipients.join('\n')} onChange={e => change('mail_recipients', e.target.value.split('\n').filter(Boolean))}/></label>}
      <label>Maximale Werkzeugschritte<input type="number" min={1} max={80} value={rules.max_steps} onChange={e => change('max_steps', Number(e.target.value))}/></label>
      <label>Maximale Änderungen pro Lauf<input type="number" min={0} max={20} value={rules.max_effects} onChange={e => change('max_effects', Number(e.target.value))}/></label>
      <label>Laufzeit in Sekunden<input type="number" min={30} max={3600} value={rules.timeout_seconds} onChange={e => change('timeout_seconds', Number(e.target.value))}/></label>
      <label>Zeitgrenze je SSH-Befehl in Sekunden<input type="number" min={1} max={600} value={rules.command_timeout_seconds} onChange={e => change('command_timeout_seconds', Number(e.target.value))}/></label>
      </details>
      <div className="dialog-actions"><button type="button" onClick={onClose}>Schließen</button><button type="button" className="primary" onClick={() => void save()}>Zugriff speichern</button></div>
    </fieldset>}
  </section>;
}
