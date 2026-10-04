# obdaAI — Status 04.10.2026

M0-Grundlage implementiert und privat gepusht. M1 enthält eine getestete vertikale
Teilfunktion; M1 und die vollständige V1 sind noch nicht abgeschlossen. Eine separate
Proxmox-Pilotinstallation ist jetzt verfügbar; kein produktiver Dauerbetrieb.

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
- Lokal: 23 Tests bestanden, 1 PostgreSQL-Test mangels isolierter lokaler DB übersprungen.
- Ruff und strikte Mypy-Prüfung bestanden; React/TypeScript/Vite-Build bestanden.
- Browserprüfung bestanden: Login, API/SSE-Chat, Historie nach Reload, Umbenennen,
  Dark Mode, Mobilnavigation ohne horizontalen Overflow, Löschen und Logout.
  Ausschließlich synthetischer Provider; Screenshots separat lokal geprüft.
- Alembic upgrade lokal auf SQLite bestanden; PostgreSQL upgrade/downgrade/upgrade und API-Persistenz in CI bestanden.
- Live Mac mini: zwei synthetische JSON-Proben bestanden. Neuer Hub-Routercode
  nach expliziter backendbezogener Thinking-Option live bestanden: lokale Inlineantwort
  auf synthetische Frage, 4,720 s Einzelmessung (kein Benchmark). Initialer Test ohne
  Option endete nach 30 s im Timeout; kein Cloudfallback. Bestehender gruppengeschützter
  Inference-Key nur im Arbeitsspeicher für diesen Smoke eingelesen, keine Rechte geändert.
  Zweiter Live-Smoke: genau 1 Router-HTTP-Aufruf mit Inlineantwort, 4,292 s; separater
  lokaler Stream mit Completion-Marker bestanden, 1,092 s. Keine echte Cloudanfrage. End-to-End-Verbindung von
  Work-Mac via Tailnet-DNS derzeit nicht verfügbar; kein Zieldeployment behauptet.
- Source-Scan bestanden. CI #37220204590 am Codecommit 012a7d0 vollständig grün:
  Python/PostgreSQL, Frontend/Browser, gitleaks und gepinnter Containerbuild.
  Draft-PR: https://github.com/sschluet/obdaAI/pull/1 .

## Offene Arbeit / echte Grenzen
- M1: automatischer lokaler asynchroner Titelworker auf vorhandener Procrastinate-Queue, Nachrichtenedit/retry,
  Volltext-Historiensuche, Provider-/Modellverwaltung mit Verbindungstests und Limits,
  abgenommener Ziel-Workerbetrieb, vollständige Live-Routing-/Streamingabnahme und Budgetkontrolle.
  PostgreSQL-Queue und persistente SSE-Wiederaufnahme implementiert; Zielbetrieb und
  automatische stalled-Reconciliation sind noch offen.
- M2: Projekte/Uploads/Quellen, echte Websuche, Obsidian-Leseadapter und Konflikt-/Löschsync.
- M3: Tools/MCP/REST/Browser, Skills/Freigaben, echte n8n-Workflows, Tasks und HA-Wartung.
- M4: isolierte Artefaktpipeline mit echten Dateien, Vorschau/QA und Folgeversionen.
- M5: direkte OpenAI/Anthropic, Last/Sicherheit/Backup-Restore und separate Linux-Ziel-VM.
- Vorhandenes n8n 2.7.5 läuft auf Mac mini; API-Key/Workflow-/Credential-Inventar offen.
  Keine neue n8n-Instanz oder zweite Terminierung starten. Migration vor Zielabnahme nötig.
- Bestehender Syncthing-Vault bleibt kanonisch. Memory-Pfadfreigabe ist noch festzulegen.
- Separate neue Proxmox-VM ausdrücklich autorisiert und provisioniert. Bestehende
  Dienste bleiben erhalten. Private Ziel-/Zugangsdaten und Prüfbelege liegen nur in `.local/`.

## Fortsetzungspunkt
Draft-PR #1 sichert den Teilstand; Head-CI vor Merge prüfen.
Danach M1 vervollständigen: lokale
asynchrone Titel mit Schutz manueller Titel, Edit/Retry mit revisionsgebundenen Labels,
Provider-/Capability-UI und Budgets; echte lokale Livechecks über den vorgesehenen
Linux-Netzpfad. Erst danach M2. Keine Routinefreigaben, aber Produktion/Cloudtransfer
und n8n/Vault-Schreibzugriff benötigen konkrete Policy-/Zielentscheidungen.

## Git-Checkpoint
Arbeitsbranch milestone/m1-chat; M0 auf main, M1 bleibt in Draft-PR #1.
Letzter Code-/Testcommit 78f3cf7 ist gepusht; CI #37221934013 vollständig grün.
Der abschließende Dokumentationscommit ändert nur diesen Statusnachweis.
Vor Freigabe/Merge den jeweils aktuellen PR-Head prüfen.
Alle Quelländerungen werden beim Checkpoint committed/gepusht; persönliche
Runtime-Dateien, Testdaten und Screenshots bleiben ignoriert.

Head-CI b83846f deckte einen mehrdeutigen Browserselektor auf: Aktionsbutton und
neues Gespräch besitzen denselben sichtbaren Namen. Testselektor auf den
Navigationsaktionsbutton begrenzt; lokaler Browsercheck und abschließende
PR-CI #37220204590 bestanden. Offizielle Actions aktualisiert/gepinnt und
Runner auf ubuntu-24.04 festgelegt; doppelte Push-/PR-Läufe entfallen. Kein Produktivfehler
oder Datenverlust aus dieser synthetischen Prüfung. Öffentliche Provider-IP kann
nicht als lokal deklariert werden (zusätzlicher Negativtest bestanden).

## M1 Fortsetzung: dauerhafte Chat-Ausführung
- Procrastinate 3.10.0 integriert; eigenes PostgreSQL-Queue-Schema via Alembic 0003.
- Atomarer Commit von Nachricht, Run und Queue-Job; aktiver Run reserviert das Gespräch
  bereits in queued. Eigenständiger Worker, Concurrency 1, keine Zeitpläne.
- SSE-Ereignisse persistent mit Cursor; Browser-Reload/Schließen beendet die Ausführung
  nicht. Laufendes Gespräch erneut öffnen verbindet die UI zum Run.
- SQLite nur lokaler Entwicklungsrunner; PostgreSQL-API-Restart lässt Runs unverändert.
- Inhaltssuche ergänzt (Substring, keine linguistische PostgreSQL-Volltextindizierung).
- Bei manueller Wiederaufnahme nach nachgewiesenem Workercrash: Teilantwort aus
  Ereignissen herstellen, interrupted markieren, keinen Provider automatisch wiederholen.
- Lokal 28 Tests bestanden, PostgreSQL-Integration mangels lokaler DB übersprungen.
  CI #37221934013: 29 Tests bestanden, einschließlich echter Queue, atomarem
  Rollback, API-Restart, Worker und Crash-Reconciliation ohne zweiten Provideraufruf.
  Dieser Abschnitt ist ein Teilcheckpoint; M1/V1 bleiben offen.

Abschließende Nachweise: Code-/Testcommit 78f3cf7; CI #37221934013 vollständig grün
(Python/PostgreSQL 29 Tests, Frontend/Browser, gitleaks, Container). Lokaler
Browser-Smoke mit Reload während laufender Antwort bestanden; Screenshot geprüft.
Wheel/Sdist gebaut und auf Worker-Module sowie Ausschluss privater Runtime-Dateien geprüft.
Die CI-Fehler in caf676b/86b0fd8 betrafen SQL-Skriptübergabe und Worker-Pooloptionen;
beide sind korrigiert und durch die tatsächliche PostgreSQL-Integration nachgewiesen.
Kein produktives Deployment und keine neue Live-Cloudanfrage.

## Proxmox-Pilotinstallation
- Dedizierte Debian-13-VM: 4 vCPU, 8 GiB RAM, 80 GiB Disk, eigener PostgreSQL-18-Datenträger.
  Offizielles Cloud-Image mit SHA512 geprüft; Docker-Paketversionen im privaten Betriebsbeleg.
- Deployter Appstand: 3c6dd2f; eigenes API-/Worker-Image, Alembic bis 0003 angewandt.
  App läuft als UID 10001, ohne Capabilities, mit schreibgeschütztem Dateisystem.
  UID-basierte ausgehende Netzwerksperre erlaubt nur lokale Datenbank und Modellrelay.
- Anmeldung, 401 ohne Anmeldung, gesperrtes Cloud-opt-in und echter lokaler Chat auf
  der installierten VM bestanden: synthetische Antwort „2 plus 2 ist 4“, Run succeeded,
  Provider local, 6,579 s Einzelmessung. Keine echte Cloudanfrage.
- Der Modellrelay läuft jetzt direkt auf der VM als systemd-Dienst mit eigenem Schlüssel.
  Auf dem Mac mini ist ausschließlich dafür der neue Benutzer hub-relay zugelassen:
  Public-Key vom VM-Ursprung, nur lokaler Modellport, keine SSH-Sessions oder weiteren
  Forwardings, kein Administrator und kein nutzbares Passwort. macOS-PAM-kompatible
  Kontoshell /bin/sh wurde separat ausdrücklich erlaubt; SSH-Shell bleibt gesperrt.
  Der Arbeits-Mac vermittelt keine Modellanfragen mehr. Browserzugang bleibt vorerst
  ein SSH-Loopback-Pilot; privates HTTPS für direkten Netzwerkzugang steht noch aus.
- Generische Installationsdateien und Betriebsgrenzen stehen in `deploy/README.md`.
  Ältere Nachweise oben beschreiben den Entwicklungsstand vor dieser Pilotinstallation.
- Live-Unterbrechung bestanden: SSE geschlossen, ausschließlich neue API neu gestartet,
  unabhängiger Worker beendet den lokalen Run erfolgreich; Antwort und Session bleiben erhalten.
- Öffentliche ausgehende TCP-Verbindung als App-UID blockiert. Eigener PostgreSQL-Dump
  mit AES-GCM verschlüsselt und entschlüsselt in eine getrennte Testdatenbank zurückgespielt:
  1 synthetisches Gespräch, 2 Nachrichten. Kein automatischer Backupplan eingerichtet.
- Bestehende VM-, Storage-, Netzwerk-, DNS- und Firewallkonfiguration nach der Installation
  gegen den privaten Vorherbeleg geprüft: unverändert. Vollständiger Reboot der neuen VM jetzt bestanden.

## Direkter Modellrelay: Abnahme
- Eigener systemd-SSH-Relay auf der neuen VM, eigener dort erzeugter Schlüssel;
  bestehende Deploy-Schlüssel verbleiben auf dem Arbeits-Mac.
- Echter lokaler Chat über den direkten Pfad bestanden. Shell/Befehle, fremder Zielport
  und Remote-Forwarding mit dem neuen Schlüssel tatsächlich abgewiesen.
- Bestehende effektive SSH-Regeln für codex-deploy gegen Vorherbackup unverändert geprüft.
  Keine gemeinsame SSH- oder Modellservice-Neustarts auf dem Mac mini.
- Neue VM vollständig neu gestartet: Relay, Egress, Docker und gesunde API automatisch
  wieder verfügbar. Öffentliche App-Egress-Verbindung auch nach Boot blockiert.
- Arbeits-Mac-Modellrelay beendet; nur Browser-SSH-Forwarding bleibt für den Pilot.
  Privates HTTPS und automatischer Backupplan bleiben offen. M1/V1 bleiben Teilstand.
