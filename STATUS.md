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
- M1: Nachrichtenedit/retry,
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
Danach M1 vervollständigen: Edit/Retry mit revisionsgebundenen Labels,
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

## Privater HTTPS-Endpunkt
- Eigenständiger Nginx-Proxy auf der neuen VM: nur private IPv4-Bindung an 443,
  keine HTTP-Standardseite oder öffentliche Zertifikatsanforderung. Separate API
  mit exakter HTTPS-Origin und Secure/HttpOnly/SameSite-Cookie; gleicher DB-/Workerstand.
- Eigene INPUT-Regeln erlauben nur die geprüften privaten Clientnetze. Proxy-UID
  ausgehend auf die lokale HTTPS-API beschränkt; keine globale Firewallkonfiguration geändert.
- Einzelnes selbstsigniertes EC-Serverzertifikat, CA:FALSE, ServerAuth und geprüfte SAN.
  Privater Schlüssel nur root auf der VM. Kein globales Clientvertrauen installiert;
  Zertifikat, Fingerabdruck und manuelles, hostbezogenes SSL-Importskript liegen privat lokal.
- Direkter HTTPS-Live-Smoke mit exakt diesem Zertifikat bestanden: Anmeldung,
  Secure-Cookie, falsche Origin/fehlender CSRF abgewiesen, echte lokale Antwort,
  Cloud weiterhin deaktiviert. Falscher TLS-Hostname wird abgewiesen.
- Vollständiger Reboot der neuen VM mit gesunder HTTPS-API/Nginx und aktivem lokalen
  Modellrelay bestanden. Proxy-Public-Egress gesperrt. Bisheriger SSH-Pilot bleibt verfügbar.
- Offen: Nutzerfreigabe des Zertifikats und sichtbare Browserabnahme des direkten
  HTTPS-Endpunkts, stabile DHCP-Reservierung, Zertifikatserneuerung und Backupplan.
  Ältere Abschnitte dokumentieren den Zustand vor diesem HTTPS-Schritt.

## Sicherung und Zertifikatsfreigabe
- Hostbezogenes SSL-Vertrauen des einzelnen Serverzertifikats im macOS-Benutzer-
  Schlüsselbund eingetragen; macOS verify-cert für die exakte IP erfolgreich.
  Fingerabdruck-Tippfehler im privaten Importskript anhand des ursprünglichen
  Serverbelegs korrigiert. Der erste Versuch hatte vor Änderung sicher abgebrochen.
- Safari zeigt die direkte HTTPS-Anwendung nach Reload. Vollständige Browser-
  Vertrauensabnahme bleibt offen: Safari zeigt noch „Nicht sicher“, der eingebaute
  Codex-Browser lehnt das Zertifikat mit ERR_CERT_AUTHORITY_INVALID ab.
  Keine Warnung umgangen oder Namensprüfung deaktiviert.
- Tägliche age-Sicherung auf eigener VM eingerichtet, 03:00 Europe/Berlin plus
  maximal zehn Minuten Verzug. Öffentlicher Empfänger auf der VM; separater privater
  Wiederherstellungsschlüssel ausschließlich auf dem Arbeitsplatz.
- PostgreSQL und Betriebskonfiguration werden ohne Klartext-Staging verschlüsselt,
  mit SHA256-Beleg atomar veröffentlicht. Erster Backup-Lauf bestanden. Schreib-/
  Netzwerkgrenzen, Sperrdatei und Speicherreserve gesetzt; kein automatisches Löschen
  veröffentlichter Sicherungen.
- Ein vollständiger verschlüsselter Snapshot auf dem Arbeitsplatz abgelegt;
  isolierter Restore und Konfigurationsentschlüsselung separat geprüft.
- Offen: automatische Off-VM-Kopie/Alarmierung, Aufbewahrungspolicy, DHCP-Reservierung
  und Zertifikatserneuerung. M1/V1 bleiben Teilstand.

## M1-Fortsetzung: lokale automatische Titel (2026-10-04)

- Nach erfolgreicher Antwort reserviert dieselbe PostgreSQL-Transaktion genau einen
  Titelauftrag. Vorhandene Procrastinate-Queue, zusätzlicher Task `hub.title`; API und
  Browser dürfen danach geschlossen werden. Ein Worker-Slot für Chat und Titel.
- Titel ausschließlich über den gepinnten lokalen Provider mit finalem Privacy-Check,
  maximal 80 Zeichen, begrenzter Kontext aus den ersten zwei Nachrichten, strukturierte
  JSON-Validierung, keine Cloudübertragung und kein Fallback. Titel bleiben private Derivate.
- Atomare Zustände (Alembic 0004); manuelle Titel haben Vorrang, auch bei gleichzeitigem
  Modellaufruf. Gelöschte Gespräche werden nicht wiederhergestellt. Fehlgeschlagene oder
  unterbrochene Titel behalten den Originaltitel; keine automatische Modellwiederholung.
  Stalled-Redispatch markiert laufende Titel als interrupted. Automatische Stalled-Erkennung
  bleibt wie bei Chat-Aufträgen offen.
- UI aktualisiert ausstehende Titel ohne Neuladen und stoppt Abfragen nach Endzustand;
  SQLite bleibt nur die Entwicklungsvariante ohne dauerhafte Queue.
- Lokal: 40 Python-Tests bestanden, PostgreSQL-Test ohne lokale Test-DB übersprungen;
  Ruff, Mypy, TypeScript/Build und Source-Scan bestanden. Cua-Browsercheck mit synthetischem
  Provider: asynchroner Titel erscheint, manueller Titel und Antwort bleiben nach Reload.
  CI prüft zusätzlich echte PostgreSQL-Transaktionsrollback, Worker und Alembic up/down.
- Direkte HTTPS-Browserprüfung in diesem Schritt durch Browser-Sicherheitsrichtlinie
  blockiert; keine Warnung umgangen. Zieldeployment und lokaler Live-Titeltest bestanden (siehe unten).
- Codecommit 6f520cf: CI #37228021113 vollständig grün, einschließlich 41 Tests mit
  PostgreSQL, Browserchecks, gitleaks und Containerbuild. Private Repo-Identität erneut geprüft.
- Eigene VM104 auf Image obdaai:6f520cf aktualisiert; API, HTTPS-API und Worker am neuen
  Image, Schema 0004. Image-ID sha256:903d508895a59d52bb6c83a9e5732f81b97c317301b4b81ec04b4715dcd01449.
  Vorher verschlüsseltes Backup, bisheriges Image und Compose-Konfiguration für Rückwechsel
  behalten. PostgreSQL selbst, bestehende VM101–103 und Proxmox-Konfiguration unverändert.
- Reales lokales Qwen-Modell über VM-Relay und zertifikatsgeprüftes HTTPS: Antwort nach
  12,085 s, Titelauftrag zu diesem Zeitpunkt noch running; gültiger 32-Zeichen-Titel nach
  insgesamt 15,480 s. Einzelmessung, kein Benchmark. Nach manuellem Umbenennen und einer
  weiteren lokalen Antwort bleibt der manuelle Titel erhalten. Cloud deaktiviert,
  Nachrichten LOCAL_ONLY. Beide APIs healthy; Backup-Timer, Relay, Egress und Nginx aktiv.
  Prüfbelege enthalten nur synthetische Abnahmedaten und liegen ausschließlich in `.local/`.
- M1 bleibt Teilstand. Nächster Funktionsschritt: Nachrichtenedit/Retry mit revisionsgebundenen
  Labels. Direkte Browser-TLS-Abnahme, automatische Off-VM-Sicherung und Alarmierung offen.

## M1: Bearbeiten, Retry, Volltextsuche und Worker-Recovery
- Bearbeiten erzeugt eine neue Nachrichtenrevision; ohne neue explizite Freigabe LOCAL_ONLY.
  Folgeantworten werden aus dem aktiven Zweig genommen, bleiben in alten Runs erhalten.
  Jeder Run hält den genauen Kontext mit Label und Revision; UI-Laufhistorie zeigt alte Antworten.
- Expliziter Retry und neue Nachrichten besitzen aktionsgebundene Idempotenzschlüssel.
  Doppelzustellung startet keinen zweiten Modellaufruf. Aktive Runs sperren Bearbeiten/Retry.
- PostgreSQL: deutsche Volltextsuche mit GIN, Websearch-Syntax und aktivem Nachrichtenfilter;
  SQLite: begrenzte Entwicklungssuche. Höchstens 100 Suchresultate, kein N+1-Scan.
- Upstream-Procrastinate-Heartbeats erkennen tote Worker; interne Queue-Wartung stellt nur
  diese Chat-/Titeljobs zur Reconciliation zu. Keine Wiederholung bezahlter/teilweiser Antworten,
  keine zusätzliche fachliche Terminierungsengine. Chat priorisiert vor Titeln.
- Lokal 43 Tests bestanden, ein PostgreSQL-Test lokal übersprungen; er prüft in CI zusätzlich
  echte Heartbeat-Recovery und deutsche Wortstämme. Providerverwaltung/Budgets weiterhin in Arbeit.

## M1: Providerverwaltung, Verschlüsselung und Laufgrenzen

- Mehrere lokale/OpenRouter-Provider, AUTO-Standard je Typ, Fähigkeiten/Datenschutzklassen,
  serverseitige Endpunktallowlist, Modellkatalog und persistente synthetische Modelltests.
- AES-GCM-Secrets außerhalb des DB-Masterkeys, Einstellungsrevisionen, frische Modellpreise,
  Kostenreservierungen mit bekannten/ unbekannten Usage-Werten, Kontext-/Token-/Zeitlimits.
- Aggregierte authentifizierte Metriken, persistent begrenzter Login, sichtbare Fehler bei
  begrenzten Providerantworten. Dreizehn synthetische Routerfälle für echte lokale Auswertung.
- Lokale Prüfung: 56 Tests bestanden, PostgreSQL-Test wird separat in CI ausgeführt;
  Lint, Typprüfung und Frontendbuild bestanden. Browser: Verbindung/Modelltest und
  Einstellungsänderung mit Revision nachgewiesen; Fixture hat keine echten Modelldaten.
- OpenRouter-Schlüssel vom Benutzer bereitgestellt; Freigabe für eigene VM und synthetische
  Live-Abnahme bis 0,05 USD liegt vor. Serveraktualisierung und Live-Nachweise folgen;
  hiermit wird noch keine vollständige M1-Abnahme behauptet.

- Vor Deployment korrigiert: SQLAlchemy-Insert quotet den reservierten PostgreSQL-Spaltennamen
  `window` in der Login-Migration; erneute CI prüft Upgrade/Downgrade/Upgrade.

- Echtes lokales Dataset: zunächst 7/13 bestanden; unklare Modell-/Fähigkeitsregeln
  gezielt verbessert, danach 13/13 bestanden (Einzelzeiten 6,03–8,69 Sekunden).
  Erweiterte Anschlussfragen und tatsächliche HTTP-Aufrufzähler ergänzen den nächsten Check.
- Eigene VM aktualisiert auf 5dd1776, Schema 0008; HTTPS/APIs/Worker gesund. Echte lokale
  und OpenRouter-Verbindungs-/Modelltests bestanden. Verschlüsselte neue Sicherung
  kopiert, Prüfsummen und isolierter Restore auf Schema 0008 bestanden; gesicherter
  Masterkey entschlüsselt DB-Providersecret. Vorhandene Proxmox-Konfiguration unverändert.
