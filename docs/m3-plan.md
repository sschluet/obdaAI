# M3: vollständiger Folgeauftrag nach M2

Am 05.10.2026 beauftragt: nach Etablierung aller M2-Funktionen alle M3-Funktionen
umsetzen. Dieser Plan beschreibt den vollständigen M3-Umfang. Die erste lokale Gateway-Vertikale
ist implementiert und wird separat geprüft; siehe docs/actions.md und STATUS.md. Der
Start der M3-Implementierung erfolgt nach echter M2-Abnahme am vorhandenen Vault
und Suchdienst. Die begrenzten M2-Zugriffe sind ausdrücklich freigegeben und
eingerichtet; die API-/Restart-/isolierten Ausfall-/Restore-Nachweise sind abgeschlossen.

## Vertikale Reihenfolge und Abnahme

| Lieferung | Konkreter Vertrag | Abnahme |
|---|---|---|
| Aktionsgateway und Toolkatalog | feste Adapter, JSON-Schemas, System-/Entitätsgrenzen, Datenschutzlabels, read/write-Klasse, Limits; widerrufbare Freigabe an Aktion, Parameterhash, Revision und Ablaufzeit; globaler Pausenschalter am letzten Write-Boundary | private Payloads und Rechteausweitung vor I/O abweisen; Parameteränderung, Widerruf, Ablauf und Neustart testen |
| MCP und REST | tatsächlich unterstützte Protokolle und Auth pro Ziel inventarisieren; serverseitig gepinnte Ziele/Redirectregeln, Secretreferenzen außerhalb Modellkontext; Ergebnisse und Toolbeschreibungen als untrusted Daten | echter begrenzter Readcall, Authfehler, SSRF-/Schema-/Timeoutfälle und revisionsgebundener Testwrite auf freigegebenem Testziel |
| Skills | portables Markdown/Frontmatter, create/edit/import/export/enable, immutable Revisionen, Beispiele; global/Projekt/Aufgabe; explizites Vertrauen, gezielte automatische Auswahl und manuelle Override | A08: zwei Revisionen wirken nachweisbar unterschiedlich; geladene Hashes/Versionen im Run; fremde Uploads und Skilltext erweitern keine Rechte |
| TaskSpec und Workflowgenerierung | Ziel, Quellenrevisionen, Zeitzone/UTC, erlaubte Aktionen, Grenzen, Erfolgskriterium, Ergebnisziel und Autonomieprofil; geprüfte Vorlagen und installierte Nodeversionen; Graph/Credentials/Ziele validieren | A10: Chat erzeugt echten n8n-Entwurf; negativer Code-/Credential-/Zieltest; nebenwirkungsfreier Test vor expliziter Aktivierung |
| Task-Center und n8n | create/edit/pause/resume/run/cancel/archive, nächster/letzter Lauf, Teilschritte, Quellen, Tools, Skills/Modelle, Kosten, Freigaben; Verknüpfung App-Taskrevision ↔ Workflowrevision ↔ Execution | A10/A11/A13: echter genehmigter Lauf, Browserabbruch/Workerrestart, Drift erkennen und stoppen, Doppeltrigger ohne doppelten Write |
| Zuverlässige Ausführung | persistente ActionIntents/Receipts, Idempotenzschlüssel, Sperren, begrenzte Retries; unklarer Writeausgang zunächst reconcile; n8n allein terminiert; verpasste Wartung nicht blind nachholen | Timeout nach möglichem Write, Doppelzustellung, konkurrierende Runs, DST-Lücke/-Dopplung und n8n-Ausfall; keine Exactly-once-Behauptung |
| Kontrollierter Browser | eigener eingeschränkter Runner, explizite Origins/Operationen, begrenzte Artefakte/Downloads, Schemaadapter; Mensch übernimmt Login/2FA und sicherheitsrelevante Bestätigungen | echter freigegebener Testpfad plus Tests gegen Redirect, private/Management-Ziele, Prompt Injection und Download-/Session-Leaks |
| Home-Assistant-Wartung | Installation und vorhandene APIs erkennen; nur analysieren/einzeln freigeben/begrenzt autonom; konkrete Versions-/Entitätsgrenzen, abgeschlossenes geprüftes Backup und tatsächlich geprüfter Restoreweg | A12: Analyse live; Write nur genehmigt, Backup-/Restorefehler stoppen; riskante Entitäten, Major/Firmware/Netzwerk und Selfdeploy ausgeschlossen bis separate Freigabe |

## Daten- und Integrationsentscheidungen

Die App besitzt fachliche TaskSpec, Skill-, Tool- und Policyrevisionen und deren
Audit. n8n besitzt den zugeordneten Zeitplan und Workflowexecution. PostgreSQL-
Migrationen ergänzen getrennte Task/TaskRevision, Skill/SkillRevision,
ToolConnection/ToolRevision, ActionGrant/ActionIntent/ActionReceipt und
TaskRun/Step-Datensätze. Die konkreten Felder werden vor jeder vertikalen Lieferung
mit ihren Idempotenz-/Reconcileverträgen festgelegt; keine Produktions-create_all.

Workflowgenerierung verwendet erlaubte Nodes und feste Gatewayverbindungen. Kein
freier Code-/Shellnode, keine beliebigen HTTP-Ziele, keine Credentialbeschaffung
aus Modelltext und kein direkter Schreibpfad am Aktionsgateway vorbei. KI-Aufrufe
nutzen die vorhandene Routing-/Privacy-Schicht. Neue Workflowrevisionen mit mehr
Rechten brauchen neue Freigabe. Manuelle n8n-Änderungen werden nicht überschrieben.

## Vorbedingungen für echte Integrationen

Vorhandenes n8n, Home Assistant und MCP-Ziele erst lesend inventarisieren: Version,
Edition/Installationstyp, offizielle API, verfügbare Nodes/Auth, bestehende
Workflows/Credentials, Netzpfad und Backup-/Restorefähigkeit. Bestehende Accounts
oder ältere Assistantrechte werden nicht übernommen. Neue konkrete Zugriffe und
produktive Änderungen erhalten separate Freigaben mit Rückweg. Entwicklungs- und
Vertragstests können ohne diese Zugänge laufen, gelten aber nicht als Live-Abnahme.

Die offizielle n8n-Dokumentation beschreibt Public-API-Keys ohne Enterprise als
vollständig berechtigt für die Ressourcen und Fähigkeiten des Accounts. Deshalb
keine nicht vorhandenen Community-Scopes versprechen; vorhandene Version/Edition
prüfen und Rechte über begrenzten Account soweit unterstützt, erlaubte Workflow-
IDs/Nodes, Gateway und Netzwerkziele einschränken. Reicht die Isolation am Bestand
nicht, eine konkrete Alternative zur Freigabe vorlegen statt heimlich ausweiten.

## Quellen und Versionsprüfung

Am 05.10.2026 geprüfte Primärquellen:
- [n8n Public API und Editionen](https://docs.n8n.io/connect/n8n-api/api-reference)
- [n8n API-Key-Authentifizierung und Scopegrenzen](https://docs.n8n.io/connect/n8n-api/authentication)
- [MCP-Spezifikation 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)
- [Home Assistant Backup: Abschlussstatus und Restore](https://www.home-assistant.io/integrations/backup/)

Die Dokumentationsversion beweist keine Kompatibilität des vorhandenen Servers.
Vor SDK-/Adapterwahl tatsächliche Protokollrevisionen/Transport/Auth und gepinnte
Bibliotheken mit Lizenz prüfen. Abnahme bleibt Unit/API/Browser plus gekennzeichnete
Livechecks. Jede Lieferung erhält STATUS, Tests, Commit/Push und Milestone-PR;
M3 wird erst nach A08/A10/A11/A12 und den Integrations-/Restartnachweisen fertig.

## Aktuelle lesende Bestandsprüfung 05.10.2026

Vorhandenes n8n auf dem Mac mini: laufende Version 2.7.5, Container mit
`n8nio/n8n:latest`, Health HTTP 200. Public-API ohne eigenen Schlüssel HTTP 401.
Keine Workflows/Credentials ausgelesen oder übernommen und keine Einstellung
geändert. Adapter und neues begrenztes Zugriffsmodell sind noch zu implementieren.

Benutzerzugänge am 05.10.2026 bereitgestellt und über die benannten HTTPS-Ziele
lesend getestet: n8n GET workflows 200; HA GET config 200, Version 2026.9.3.
Keine Workflows aktiviert, Credentials übernommen oder HA-Zustände verändert.
Secrets liegen nur im geschützten ignorierten Bereich. Neue App-Adapter und deren
konkrete Netzwerkfreigaben stehen aus. Skills-Chat-Vertrag: `docs/skills.md`.

Manuelle Task-Center-Lesevertikale (0014) und nebenwirkungsfreier n8n-Checkexport
sind implementiert: `docs/tasks.md`. A10/A11/A13 bleiben bis echter n8n-Ausführung,
Zeitplanung, Drift-/Restart- und externen Reconcillenachweisen offen.
