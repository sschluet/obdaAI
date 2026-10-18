import {useEffect, useState} from 'react';
import type {IntegrationAPI, IntegrationRow} from './IntegrationRegistryPanel';

export function AgentPolicyEditor({api, integration, onClose}: {
  api: IntegrationAPI; integration: IntegrationRow; onClose: () => void;
}) {
  const [policy, setPolicy] = useState<any>(null);
  const [rules, setRules] = useState<any>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [writes, setWrites] = useState(false);
  useEffect(() => {
    let alive = true;
    api('/integrations/' + integration.id + '/agent-policy').then(p => {
      if (alive) {setPolicy(p); setRules(p.rules); setWrites(p.writes_enabled);}
    }).catch(e => {if (alive) setError(e.message);});
    return () => {alive = false;};
  }, [api, integration.id]);
  const change = (key: string, value: unknown) => setRules({...rules, [key]: value});
  async function save() {
    setBusy(true); setError('');
    try {
      let profileRevision = policy.profile_revision;
      if (writes !== policy.writes_enabled) {
        const result = await api('/integrations/' + integration.id + '/write-control', 'PATCH', {expected_revision: profileRevision, writes_enabled: writes});
        profileRevision = result.revision;
      }
      await api('/integrations/' + integration.id + '/agent-policy', 'PUT', {
        expected_revision: policy.revision, expected_profile_revision: profileRevision, rules,
      });
      onClose();
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <section className="setting-card agent-policy" aria-label={'Agentenregeln für ' + integration.name}>
    <h3>Agentenregeln · {integration.name}</h3>
    <p>Ziel: {integration.config.url}{integration.kind === 'ssh' ? ' · Konto: ' + integration.config.username : ''}</p>
    {error && <p role="alert" className="error">{error}</p>}
    {rules && <fieldset disabled={busy}>
      {!policy.current && policy.revision > 0 && <p>Das Profil wurde geändert. Die Regeln müssen erneut freigegeben werden.</p>}
      <label><input type="checkbox" checked={rules.enabled} onChange={e => change('enabled', e.target.checked)}/>Agentenzugriff für dieses Profil freigeben</label>
      <label><input type="checkbox" checked={writes} onChange={e => setWrites(e.target.checked)}/>Schreibaktionen für dieses Profil erlauben</label>
      <label><input type="checkbox" checked={rules.autonomous} onChange={e => change('autonomous', e.target.checked)}/>Erlaubte Änderungen autonom ausführen</label>
      <label><input type="checkbox" checked={rules.private_data_to_target} onChange={e => change('private_data_to_target', e.target.checked)}/>Private Agentendaten ausdrücklich auch an dieses Ziel über eine öffentliche IP übertragen</label>
      <p>Diese Freigabe gilt für das angegebene Systemkonto. Sie erlaubt keine Weitergabe an Cloudmodelle oder öffentliche Suchdienste.</p>
      <p>Ohne Autonomie hält der Agent vor jeder Änderung zur Freigabe an. Profil-Schreibrechte und die globale Schreibpause gelten zusätzlich.</p>
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
      {integration.kind === 'mcp' && <label><input type="checkbox" checked={rules.mcp} onChange={e => change('mcp', e.target.checked)}/>Aktuelle MCP-Werkzeuge innerhalb dieses Serverkontos zulassen</label>}
      {integration.kind === 'smtp' && <label>Erlaubte E-Mail-Empfänger (je Zeile eine Adresse)<textarea rows={3} value={rules.mail_recipients.join('\n')} onChange={e => change('mail_recipients', e.target.value.split('\n').filter(Boolean))}/></label>}
      <label>Maximale Werkzeugschritte<input type="number" min={1} max={80} value={rules.max_steps} onChange={e => change('max_steps', Number(e.target.value))}/></label>
      <label>Maximale Änderungen pro Lauf<input type="number" min={0} max={20} value={rules.max_effects} onChange={e => change('max_effects', Number(e.target.value))}/></label>
      <label>Laufzeit in Sekunden<input type="number" min={30} max={3600} value={rules.timeout_seconds} onChange={e => change('timeout_seconds', Number(e.target.value))}/></label>
      <label>Zeitgrenze je SSH-Befehl in Sekunden<input type="number" min={1} max={600} value={rules.command_timeout_seconds} onChange={e => change('command_timeout_seconds', Number(e.target.value))}/></label>
      <div className="dialog-actions"><button type="button" onClick={onClose}>Schließen</button><button type="button" className="primary" onClick={() => void save()}>Regeln speichern</button></div>
    </fieldset>}
  </section>;
}
