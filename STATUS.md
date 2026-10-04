# obdaAI — Status 04.10.2026

M0-Grundlage implementiert und privat gepusht. M1 enthält eine getestete vertikale
Teilfunktion; M1 und die vollständige V1 sind noch nicht abgeschlossen. Kein produktives Deployment.

## Umgesetzt
- Eigenständiges privates GitHub-Repository `sschluet/obdaAI`; Sichtbarkeit via API bestätigt.
  M0 Commit ee0cf45 auf main und milestone/m0-foundation gepusht.
- Autorisierte lesende Bestandsaufnahme, Architektur und begründete Vereinfachungen,
  Daten-/Sicherheitsmodell, Zuordnung aller 19 Anforderungen und 14 Abnahmefälle.
  Privates Bestandsprotokoll ausschließlich unter ignoriertem `.local/`.
- FastAPI, Pydantic, SQLAlchemy und Alembic; persistente Sessions, Chats, Nachrichten und Runs.
  Single-User scrypt-Login, HttpOnly-Cookie, Origin/CSRF, Loginlimit, Logout, Securityheaders.
- Lokaler strukturierter AUTO-Router mit optionaler kompletter Inlineantwort; höchstens
  eine Schema-Reparatur. Fähigkeitenliste unabhängig von Modellklasse. Kein Cloudfallback.
- Lokaler/OpenRouter-HTTP-Adapter, finaler Scope/Revision/Label-Gateway, gepinnte DNS-IP
  mit ursprünglicher TLS-SNI/Host-Prüfung, keine Redirects/Umgebungsproxies.
  Cloud standardmäßig deaktiviert; explizites Gesprächsopt-in erforderlich.
- Echte statische React/TypeScript-UI an API: SSE, Markdown/Code/Tabellen, Copy, Historie,
  Titelsuche, Umbenennen, Archiv/Löschen, Abbruch, Runfehler, Light/Dark, mobile Navigation.
  Offene Bereiche zeigen ihren tatsächlichen Entwicklungsstatus.
- Gepinnte Paket-Lockfiles und per Registry geprüfte Container-Digests; Dockerfile und
  CI für Python/Lint/Typen/Tests, PostgreSQL, Frontend/Browser, Secrets und Containerbuild.

## Nachweise
- Lokal: 21 Tests bestanden, 1 PostgreSQL-Test mangels isolierter lokaler DB übersprungen.
- Ruff und strikte Mypy-Prüfung bestanden; React/TypeScript/Vite-Build bestanden.
- Browserprüfung bestanden: Login, API/SSE-Chat, Historie nach Reload, Umbenennen,
  Dark Mode, Mobilnavigation ohne horizontalen Overflow, Löschen und Logout.
  Ausschließlich synthetischer Provider; Screenshots separat lokal geprüft.
- Alembic upgrade lokal auf SQLite bestanden; PostgreSQL-Migration in CI noch abzuwarten.
- Live Mac mini: zwei synthetische JSON-Proben bestanden. End-to-End-Verbindung von
  Work-Mac via Tailnet-DNS derzeit nicht verfügbar; kein Zieldeployment behauptet.
- Source-Scan / Paket- und Containerbuild / CI-Liveergebnisse bei Checkpoint ergänzen.

## Offene Arbeit / echte Grenzen
- M1: automatischer lokaler asynchroner Titelworker (Procrastinate), Nachrichtenedit/retry,
  Volltext-Historiensuche, Provider-/Modellverwaltung mit Verbindungstests und Limits,
  dauerhafter Workerbetrieb, vollständige Live-Routing-/Streamingabnahme und Budgetkontrolle.
  Aktueller Chat bleibt HTTP-gebunden; Hintergrundaufträge sind noch nicht implementiert.
- M2: Projekte/Uploads/Quellen, echte Websuche, Obsidian-Leseadapter und Konflikt-/Löschsync.
- M3: Tools/MCP/REST/Browser, Skills/Freigaben, echte n8n-Workflows, Tasks und HA-Wartung.
- M4: isolierte Artefaktpipeline mit echten Dateien, Vorschau/QA und Folgeversionen.
- M5: direkte OpenAI/Anthropic, Last/Sicherheit/Backup-Restore und separate Linux-Ziel-VM.
- Vorhandenes n8n 2.7.5 läuft auf Mac mini; API-Key/Workflow-/Credential-Inventar offen.
  Keine neue n8n-Instanz oder zweite Terminierung starten. Migration vor Zielabnahme nötig.
- Bestehender Syncthing-Vault bleibt kanonisch. Memory-Pfadfreigabe ist noch festzulegen.
- Neue VM-ID/Adresse, Proxmox-Kapazitätsprüfung und konkrete Provisionierungsfreigabe offen.
  Alte Deploytoken-Freigaben werden nicht automatisch für neue Ressourcen verwendet.

## Fortsetzungspunkt
Zuerst CI-Ergebnisse prüfen/fixen und diesen M1-Teilstand per Draft-PR sichern.
Danach M1 vervollständigen: PostgreSQL-Procrastinate-Migration/Worker und lokale
asynchrone Titel mit Schutz manueller Titel, Edit/Retry mit revisionsgebundenen Labels,
Provider-/Capability-UI und Budgets; echte lokale Livechecks über den vorgesehenen
Linux-Netzpfad. Erst danach M2. Keine Routinefreigaben, aber Produktion/Cloudtransfer
und n8n/Vault-Schreibzugriff benötigen konkrete Policy-/Zielentscheidungen.
