# obdaAI — Status 05.10.2026

## M2 in Umsetzung

Implementiert: Projekträume, scoped Quellenchat, unveränderte gehashte Originale,
asynchrone Extraktion, Office-/PDF-/Text-/Tabellen-/Bildformate, Fundstellen, lokale OCR,
strukturierte Decimal-Tabellenprüfung, öffentliche SearXNG-Recherche und gezielter
allowlistgeschützter HTML-Abruf. Oberfläche für Projekte/Uploads/Suche/Quellen und
Memory mit Herkunft, Revisionen und Konfliktvergleich; kanonisches Markdown,
read-only Allgemeinvault, begrenzte Memorywrites, Tombstones und Crash-Reconciliation.
Direktes `Merke dir:` ist source-/revisiongebunden und idempotent, ohne Modellwrite.

Bisher lokal 84 Tests bestanden, PostgreSQL separat in CI. Browser mit synthetischen
Dateien: Projekt anlegen, Mehrfachupload, Fundstellensuche, exakte Summe 12.50,
Quellenchat und explizites Memory bestanden. Keine echte Obsidian-Abnahme behauptet.

Noch offen vor vollständiger M2-Abnahme: finale CI und eigener Serverrollout einschließlich
Offline-Parser/Landlock/OCR, echte Quellenantwort und Sicherungsrestore; echte vorhandene
Vault- und Suchanbindung mit eigenen begrenzten Zugängen. Vorhandener Vault und JSON-
Suchdienst wurden ausschließlich lesend bestätigt. Separate Zugriffsfreigabe für allgemeinen
Vault readonly und AI/Memory write wurde angefragt und steht noch aus. Bestehender Sync
und andere Plattformressourcen wurden nicht verändert.

M2 bleibt bis zu diesen Nachweisen unvollständig. Nächster Schritt: getesteten Checkpoint
pushen, CI/Browser/Container prüfen, own-VM-Dateipipeline installieren und live abnehmen;
dauerhafte vorhandene Verbindungen erst innerhalb bestätigter Zugriffsfreigabe einrichten.

---

# obdaAI — Status 04.10.2026

M1 ist implementiert und auf der eigenen Proxmox-VM mit echten lokalen und OpenRouter-
Aufrufen geprüft. Die vollständige V1 umfasst zusätzlich M2–M5 und ist noch nicht fertig.
Der finale Codecheckpoint 244355d ergänzt automatische Preisaktualisierung, sichtbare
Testrevisionen und reproduzierbare Masterkey-Erzeugung. CI 37232870330 ist vollständig
grün; dieselbe Version läuft mit gesunden APIs/Worker auf der eigenen VM. Die folgenden historischen Abschnitte dokumentieren
Zwischenstände und sind keine aktuelle Liste offener M1-Funktionen.

## M1 geliefert

- Single-User-Login, persistente Sessions, CSRF/Origin, sichere Cookies, datenbankgestütztes
  Loginlimit über beide API-Prozesse und Neustarts, Logout und Securityheader.
- Persistenter AUTO-Chat, SSE mit Wiederaufnahme, Markdown/Code/Tabellen/Copy, Light/Dark,
  Tastaturbedienung und mobile Navigation. Lokaler Router trennt Fähigkeiten und Modellklasse.
- Edit mit revisionsgebundener erneuter Inhaltsfreigabe, explizites idempotentes Retry,
  Abbruch, alte Kontexte/Antworten als Laufversionen, deutsche Volltextsuche, Archiv/Löschen.
- Asynchrone lokale Titel mit Schutz manueller Titel; Procrastinate-Queue auf PostgreSQL,
  Chatpriorität, Heartbeats und automatische Reconciliation ohne erneute Inference.
- Mehrere freigegebene lokale/OpenRouter-Provider, AUTO-Standard je Typ, Katalog-/Modelltests,
  Fähigkeiten, Kontext-/Token-/Zeitlimits, serverseitige Endpunktfreigabe und Konfigurationsrevisionen.
- AES-GCM-Secrets mit getrenntem Masterkey, konservative Budgetreservierungen, gemeldete
  gegenüber unbekannten Kosten, begrenzte Gesamt-/HTTP-Laufzeit und sichtbare Streambegrenzung.
- Finale Label-/Scope-/Revision-Prüfung am Providerpayload; keine Rechte aus Routertext,
  kein Cloud-Fallback. Generische Defaults bleiben LOCAL_ONLY und Cloud deaktiviert.
  Die eigene VM wurde separat für synthetische OpenRouter-Abnahme bis 0,05 USD freigegeben.
- Authentifizierte aggregierte Laufmetriken; Schema 0008; eigener HTTPS-/Worker-/DB-Betrieb,
  verschlüsselte Sicherung, Off-VM-Kopie, isolierter Restore und Rückfallimage.

## Überprüfbare Abnahme

- Finaler Codecheckpoint 244355d: CI 37232870330 vollständig grün, 68 Tests einschließlich
  echter PostgreSQL-Migration Upgrade/Downgrade/Upgrade, Queue und Recovery; Browser,
  Typen/Lint, Secret-Scan und gepinnter Containerbuild bestanden.
- Lokal 67 Tests bestanden, PostgreSQL wird separat in CI geprüft. Frische, fehlende,
  veraltete und nicht verfügbare Modellpreise inklusive privater Nicht-Übertragung geprüft.
- Echtes lokales Dataset: 15/15 bestanden, jeder Fall genau ein Router-HTTP-Aufruf,
  einfache Inlineantworten, Kontextanschlüsse, Cloudklasse, kombinierte Fähigkeiten und
  zitierte Prompt-Injection. Einzelzeiten 5,83–8,70 s; kleine synthetische Stichprobe,
  kein Beweis allgemeiner Modellqualität oder einer Produktionslast-SLA.
- Eigene VM: echte lokale und OpenRouter-Verbindungs-/Modelltests; private komplexe Frage
  bleibt lokal, freigegebene gleiche Frage verwendet OpenRouter. Gemeldete Kosten der
  Cloudantwort 0,0002192 USD, vorherige Reservierung 0,0006308 USD.
- Sendewiederholung/Retry ohne Duplikate, Edit mit erhaltenem altem Kontext, deutsche
  Volltextsuche, Client-Disconnect ohne Jobverlust, Abbruch und persistente SSE bestanden.
- Echter Worker-Neustart: API blieb gesund, Heartbeat-Recovery nach 83,45 s, Status
  interrupted statt erneuter Inference. Echte eigene Relay-Unterbrechung: Fehler ohne
  Cloud-Fallback, gleiche unveränderte Verbindung wiederhergestellt; Mac mini nicht geändert.
- Grenzen live: deaktivierter lokaler Router, zu großer Kontext, Nullbudget und tatsächlich
  durch Tokenlimit begrenzter OpenRouter-Stream bestanden. Kosten/Reservierungen dieser
  Abnahme zusammen 0,0004836 USD; offene Usage bleibt unbekannt und reserviert.
- Verschlüsselte DB/Config-Sicherung kopiert und geprüft; isolierter Restore Schema 0008,
  Providersecret mit gesichertem Masterkey entschlüsselt. Vorhandene Proxmox-Konfiguration
  gegen Baseline unverändert. APIs ca. 72/77 MiB, Worker 130 MiB, DB 114 MiB bei einer
  einzelnen Messung; kein Lastbenchmark. Private Prüfbelege bleiben im ignorierten .local/.

- Finale Liveprüfung auf 244355d: abgelaufene Metadaten simuliert, privates Gespräch
  blieb ohne externe Preisprüfung lokal; freigegebene Cloudfrage aktualisierte den echten
  offiziellen Katalog und antwortete erfolgreich. Gemeldete Antwortkosten 0,0001976 USD.
  Aktuelle lokale/OpenRouter-Modelltests passen zur jeweiligen Einstellungsrevision.
  Gesamte gemeldete Kosten plus offene Reservierungen nach Abschluss: 0,0006928 USD.
- Abschlusssicherung erneut verschlüsselt kopiert und isoliert wiederhergestellt: Schema 0008,
  28 synthetische/Pilot-Gespräche, 52 Nachrichten, Masterkey entschlüsselt Providersecret.
  Bestehende Proxmox-Konfiguration weiterhin identisch; finale aktive Chatqueue leer.

## Verbleibender V1-Umfang und Betriebsgrenzen

- M2: Projekte/Uploads/Quellen, echte Websuche, Obsidian und Memory-/Konflikt-/Löschsync.
- M3: Tools/MCP/REST/Browser, Skills/Freigaben, n8n/Tasks und HA-Wartung; bestehendes n8n
  und Vault-Sync zuerst inventarisieren, keine zweite Terminierungsengine.
- M4: echte DOCX/PPTX/PDF/Bild-Artefakte, isolierter Runner, Vorschau/QA und Versionen.
- M5: direkte OpenAI/Anthropic-Adapter, breite Last-/Sicherheits- und reale Geräteabnahme,
  automatische Off-VM-Kopie/Alarmierung/Aufbewahrung und Zertifikatserneuerung.
- HTTPS ist mit exakt verifiziertem Zertifikat an der API abgenommen; direkte Browser-
  Zertifikatsabnahme blieb durch Browser-Sicherheitsregeln blockiert. Kein Warnungsbypass.
  Der ausdrücklich eingerichtete SSH-Pilot bleibt als bestehender Testzugang erhalten.
- Inference bleibt auf dem vorhandenen Mac mini; App/API/Worker auf eigener VM. Der
  Arbeits-Mac wird für deren Ausführung nicht benötigt. Recovery-Identität getrennt sichern.
- OpenRouter-Testbudget zunächst 0,05 USD pro UTC-Monat; andere Budgets erfordern eine
  bewusste Änderung. Reservierungen sind Schätzungen, kein hartes Provider-Kontolimit.

## Git und Fortsetzung

Arbeitsbranch milestone/m1-chat, privates Repository sschluet/obdaAI, PR #1.
Alle Quelländerungen werden pro Checkpoint geprüft, committed und gepusht. Die genaue
Auslieferung nennt finalen Commit, Head-CI, Serverimage und uncommittete Dateien.
Nächster Produktmeilenstein ist M2; M1-Live-Nachweise werden nicht durch Mocks ersetzt.

## Historische Zwischenstände

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

- Live-Regression nach Routerupdate: numerische JSON-Inlineantwort `answer: 4` war
  fachlich korrekt, aber zu strikt als Nicht-Text verworfen. Endliche Zahlen werden
  jetzt zu Text normalisiert; Booleans/NaN/Infinity und unzulässige Cloud-/Tool-Inlineantworten
  bleiben ungültig. Acht Regressionen prüfen diese Grenze.
