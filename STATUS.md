# obdaAI — Status 05.10.2026

## Aktueller Stand: M3-Schreibprofile und M4-Dateidialoge installiert

Produktiv ist `9b6f30b` / Schema 0020 installiert. Die begrenzten Aufgaben-
Schreibprofile und vier lokale Dateidialoge mit dauerhaften Versionen, Vorschau-
Freigabe und Offline-Runner sind ausgerollt. Beide APIs gesund; vorhandene
IPv4-/IPv6-Regeln, übrige Overlays und Browsercode unverändert. Vorherige
verschlüsselte Sicherung erfolgreich; neuer eigener Overlay enthält die Dateidienste.

377 lokale Tests bestanden; alle zehn echten PostgreSQL-Integrationsfälle auf der
eigenen VM bestanden. Ruff/mypy, TS/Build und Secret-Scan bestanden. Mobile
synthetische Browserabnahme einschließlich Tabellen, Folgeversionen, lokaler Entwürfe
und Chatübernahme bestanden. Echte Linux-Abnahme: vier Dateien, sechs Vorschauen.
Die erste Live-Abnahme zeigt einen bestehenden Engpass: lange Vault-Abgleiche
blockieren den gemeinsamen Upload-Worker. Queue-Trennung und nicht blockierender
Abgleich werden gerade geprüft und ausgerollt. Produktive Dateiabnahme und
verschlüsselter Schema-0020-Restore sind noch nicht abgeschlossen.

GitHub konnte mehrere Jobs wegen nicht verfügbarer Hosted Runner nicht starten;
fehlgeschlagene Allokation ist kein bestandener Test. Der konkrete Officefehler
wurde am eigenen Linux-Container diagnostiziert und behoben, ohne den
Dateisystemschutz oder die Netzwerksperre abzuschalten. Aktuelle M4-Grenzen:
[Dateiabnahme](docs/m4-acceptance-status.md). M3/M4/M5 sind noch nicht vollständig.

## Historischer Stand · M3 erweitert und live installiert

Installierte Funktionsquelle `6eeba62`, Branch `milestone/m3-actions`, Schema 0016.
CI 37315411367 vollständig grün: Python, sieben echte PostgreSQL-Prüfungen,
Frontend inklusive Desktop/Mobile/Browser, Container und Secrets. Lokal 260 Tests
bestanden; sieben PostgreSQL-Fälle separat in CI. Ruff/mypy, TypeScript und Build
bestanden. Die folgenden historischen Abschnitte dokumentieren frühere Lieferungen.

Neu verfügbar: normale MCP-Verbindungsdialoge unter Einstellungen mit verschlüsselten
Tokens, revisionsgebundener Bearbeitung und wiederherstellbarem Archiv; eigene
Chatnachricht über „Als Aufgabe planen“ in den normalen pausierten Aufgabendialog
übernehmen; Home-Assistant-Installation und Sicherungsmetadaten als lesender Bericht.
Kein realer MCP-Server gewünscht: Produktionsallowlist leer, entfernte Ausführung
nicht freigegeben. MCP ist damit noch keine vollständige externe Toolausführung.

Live auf eigener VM: beide APIs gesund, HTTPS zertifikatsgeprüft, n8n-Zeitimpuls
gesund und alle vier früheren automatischen Ergebnisse/Terminbelege erhalten.
HA-WebSocket-Lesebericht bestätigt HA OS 18.3, Core 2026.9.3, Supervisor 2026.09.3,
61 vorhandene Sicherungen, idle, null Agentfehler und laut HA zuletzt am 03.10.2026
abgeschlossene automatische Sicherung. Beleg gespeichert; Replay ohne erneuten
HA-Aufruf. Kein HA-Write, kein Backupdownload und keine Restore-Abnahme von HA.

Synthetische MCP-Verbindung auf VM angelegt, verschlüsselt, vor nicht freigegebenem
Netzwerkaufruf abgewiesen, archiviert/wiederhergestellt und abschließend archiviert;
vier Revisionen erhalten. Sonstige Projekte, Aufgaben und Aktionen unverändert.
HA-Secret nur in beiden APIs readonly; alle bestehenden IPv4-/IPv6-Regeln und fünf
Compose-Dateien bytegleich erhalten. Globale externe Schreibaktionen bleiben pausiert.
Beim Rollout erkannte die Abschlussprüfung den fehlenden expliziten Migrationslauf;
Maintenance-Migration 0015 → 0016 anschließend erfolgreich, Rollouthelper korrigiert.

Neue verschlüsselte Off-VM-Sicherung und isolierter Schema-0016-Restore bestanden:
MCP-Secret mit restauriertem Masterkey entschlüsselt, HA-Bericht wiederhergestellt,
fünf Skillrevisionen, fünf Aktionsbelege, neun Aufgabenrevisionen, acht lokale
Taskbelege (drei Modellbelege), fünf Zeitpläne, 17 Planrevisionen und vier Terminbelege
geprüft. 40 Originalhashes, sechs Memory-Dateien, begrenzte SSH-Schlüssel/Units,
Provider-/HA-/Scheduler-Konfiguration erhalten. Temporäre Restore-DB entfernt;
bestehende Proxmox-Konfiguration unverändert. Dies ist ein obdaAI-Restore.

M3 bleibt Teilstand: generische validierte Chat-zu-n8n-Workflows, externe
MCP-/REST-Ausführung mit Reconciliation, MCP OAuth/stdio, eingeschränkter
Browserrunner und konkret abgenommene HA-Wartung sind offen. HA-Schreibwartung
benötigt weiterhin einen tatsächlich überprüften Wiederherstellungsweg. Aktuelle
Begrenzungen stehen in docs/m3-plan.md und docs/requirements.md.

## Historische M3-Lieferungen · Aktionsgateway, Chat-Skills und manuelle Aufgaben

Branch `milestone/m3-actions`, auf M2 aufbauend. Implementiert: feste Werkzeuge
Hub-Status lesen und Projekt wiederherstellbar archivieren; strikte Schemas,
Vorschläge mit Request-ID/Parameterhash, befristete und widerrufbare Einzelfreigaben,
Pausenrevision am letzten Write-Boundary, atomarer lokaler Effekt mit eindeutigen
Belegen. Migration 0012 startet pausiert und schützt nichtleere Auditdaten beim
Downgrade. Keine Modelle/Quellen können Werkzeuge oder Freigaben selbst registrieren.

Werkzeuge-Oberfläche: Zielrevision vergleichen, fünf Minuten freigeben, getrennt
ausführen oder widerrufen, Pausenstatus und persistente Belege. Synthetischer
Browsercheck bestanden: Vorschlag ohne Änderung, Freigabe noch ohne Ausführung,
Archivierung Revision 2, Beleg nach Reload, finale Pause; 390px ohne horizontalen
Überlauf. Screenshot nur Fixture. Zwölf Gateway-API-/Kontrakttests bestanden;
PostgreSQL-Duplikat-/Sperrentest separat für CI vorbereitet. Lokal 110 Tests bestanden, zwei PostgreSQL-Tests für CI; Ruff/mypy, Frontendbuild
und Secret-Scan bestanden. Gateway-Commit `49b50b4`: CI 37285653819 vollständig grün, auf VM installiert,
Schema 0012. Echte synthetische Gateway-Abnahme bestanden: pausierte Writes
abgewiesen, getrennte Einzelfreigabe, Archivierung Revision 2, Duplikat ohne
zweiten Effekt, persistenter Beleg, finale Pause. Verschlüsselte Off-VM-Sicherung
und isolierter Restore auf Schema 0012 bestanden; 40 Originalhashes und sechs
Memory-Dateien erhalten. M3 nicht als fertig abgenommen.

Skills-Chat-Vertikale implementiert: portables Markdown mit strengem JSON-Frontmatter,
Import/Export, unveränderliche Revisionen, ausdrückliches Hash-/Revisionsvertrauen,
Global-/Projektscope, Stichwortauswahl und manueller Override je Gespräch. Jeder
Lauf speichert Dokumentrevision und Hash; Bearbeitung deaktiviert die neue Revision.
Neun neue API-Kontrakttests bestanden; lokal insgesamt 119 bestanden, drei PG-Checks
separat in CI. Browser: deaktivierter Import, explizite Aktivierung, neuer Entwurf sperrt
Aktivierung, Revision 2 wieder deaktiviert, beide Revisionen erhalten, Reload und
390px mit Hashumbruch, gespeicherter Override nach erneutem Laden bestätigt.
Skill-Commit `ab00975`: CI 37287217841 grün, 121 Tests einschließlich PostgreSQL
bestanden; auf VM installiert, Schema 0013, HTTPS zertifikatsgeprüft HTTP 200.
A08 mit echtem lokalen Modell bestanden: dieselbe synthetische Frage mit Revision 1
auf Deutsch, Revision 2 auf Englisch; unterschiedliche Antworten und geladene
Revisionen/Hashes im Run bestätigt. Testskills danach deaktiviert; Gateway pausiert.
Der erste Tabellen-Skill wurde vom Router als artifact eingestuft und sicher
gestoppt; diese Klassifikation bleibt offen. Bei der Live-Abnahme entdeckt:
Skill-Änderungen warteten unnötig auf die Vault-Sperre. Korrektur `5f261f9` trennt
die Skill-Sperre. CI 37288717036 grün: 122 Tests einschließlich echtem PostgreSQL-
Isolationstest bestanden; dort bleibt die Vault-Sperre während Skill-Erstellung
gehalten, die unabhängige Erstellung schließt dennoch ab. Auf VM installiert,
Schema 0013, beide APIs gesund und angemeldeter HTTPS-Zugriff zertifikatsgeprüft.
Revision 2 des A08-Skills bleibt nach Software-Neustart deaktiviert erhalten;
Gateway weiterhin pausiert.
Erweiterte verschlüsselte Off-VM-Sicherung und isolierter Schema-0013-Restore
bestanden: drei Skillrevisionen mit gültigen Dokumenthashes, drei Aktionsbelege,
40 Originalhashes, sechs Memory-Dateien und Zugangsschlüssel erhalten. Bestehende
Proxmox-Konfiguration unverändert.

Manuelle Task-Center-Vertikale implementiert, Migration 0014: unveränderliche
TaskSpec-Revisionen, getrennte Pausenrevision, Hash-/Quellen-/Skillbindung,
transaktionale PostgreSQL-Queue und atomare lokale Lesebelege. Anlegen/Bearbeiten,
Pause/Fortsetzen, Start, wartenden Lauf abbrechen und wiederherstellbares Archiv.
Nur feste lokale Leseprüfungen, kein Modellaufruf, Kosten 0 USD, kein Zeitplan.
Lokal 140 Tests bestanden, vier echte PostgreSQL-Checks für CI; Ruff/mypy,
Frontendbuild und Secret-Scan bestanden. Browser-Fixture: Lifecycle, persistenter
Lauf nach Reload, alte Revision nach Bearbeitung, Archiv/Restore pausiert und
390px ohne horizontalen Überlauf bestätigt. Aufgaben-Commit `826b06d`: CI 37292382204 vollständig grün, 144 Tests mit
allen vier PostgreSQL-Checks bestanden. Auf VM installiert, Schema 0014, beide
APIs gesund, HTTPS und angemeldete Aufgaben-API zertifikatsgeprüft HTTP 200.
Echte synthetische PG-Worker-Abnahme bestanden: ein lokaler Lesebeleg, wiederholte
Anfrage ohne zweiten Lauf, alte Revision/Beleg nach Bearbeitung erhalten,
Archiv/Restore pausiert. Kein Modellaufruf, Kosten 0 USD; Gateway weiterhin pausiert.
Verschlüsselte Off-VM-Sicherung und isolierter Schema-0014-Restore bestanden:
zwei Aufgabenrevisionen und ein Task-Lesebeleg, Skill-/Aktionsaudit,
40 Originalhashes, sechs Memory-Dateien und Zugangsschlüssel geprüft.
Bestehende Proxmox-Konfiguration unverändert. Drei zusätzliche negative Tests
für beschädigte Laufmanifeste bestanden (17 Aufgaben-Tests insgesamt). n8n-Export: streng validierter Manual Trigger → No operation,
installierte Nodeversionen lesend geprüft; separate Freigabe zum Anlegen auf dem
Bestands-n8n angefragt. Kein Workflow dort angelegt oder aktiviert. Dieser Entwurf
führt noch keine Aufgabe aus; A10 bleibt offen. Vertrag: `docs/tasks.md`.

Begrenzter Operator-n8n-Adapter ergänzt: gepinntes HTTPS-Ziel, keine Redirects,
Graph-/Statusvergleich, geschütztes Intentjournal vor POST, Sperre gegen parallele
Operatoren und Reconciliation ohne blindes Wiederholen bei unklarem Ausgang.
24 neue Tests bestanden, inklusive Versionsdrift und restriktiver Serverdefaults. Echte lesende Namenssuche erfolgreich; Erstellung ohne
konkrete Freigabe verweigert, kein Workflow verändert. Live-Erstellung am 05.10.2026 nach „alles durchführen“ erfolgt: genau ein
inaktiver Prüfworkflow, ID/Version/Hash lesend verifiziert. Serverergänzungen nur
callerPolicy=workflowsFromSameOwner und availableInMCP=false akzeptiert;
Reconciliation ohne zweiten POST. Keine Aktivierungs-/Ausführungsfunktion. `docs/n8n-connection-check.md`.

Nächste Vertikalen: Toolverbindungen, echte n8n-Ausführung/Zeitpläne und aufgabenbezogene Modell-Skills. Externe MCP/REST-/Browser-/n8n-/HA-Dispatcher und autonome
Modellaktionen sind noch nicht implementiert. Beide Benutzerzugänge am 05.10.2026 über verifiziertes HTTPS lesend bestätigt:
n8n Workflows-API 200, Home Assistant Config-API 200 / Version 2026.9.3. Secrets nur
im geschützten ignorierten Bereich, keine bestehenden Workflows oder HA-Einstellungen
geändert. Adapterinstallation und begrenzte neue Egressregeln noch offen. Keine externen
Retry-/Exactly-once- oder HA-Wartungsgarantie aus dem lokalen Gateway ableiten.
Siehe `docs/actions.md` und `docs/m3-plan.md`.


## M2 vollständig abgenommen · 05.10.2026

Funktionaler Stand `92babc4` auf der eigenen VM installiert, CI 37281892751 grün,
Schema 0011, beide APIs gesund. Lokal 98 Tests bestanden; zusätzlicher PostgreSQL-
Test in CI. Browser: mobile blaue Oberfläche, erhaltener Entwurf bei HTTP 409,
aktuelle Einzelnotiz zum Vergleich, ausdrückliche Hash-/Revisionsbindung, Revision 6.

Echte M2-Abnahme am vorhandenen Vault und Suchdienst bestanden: neun Dateiformate,
Original-SHA/Fundstellen/Decimal/Scopeisolation und unverändertes lokales Modell;
kanonisches Schreiben, idempotentes Anlegen, externe Änderung geschützt, explizite
Auflösung, stabile ID nach Rename, Versionen, wiederherstellbare Archivierung,
kein Wiederbeleben nach Abgleich und tatsächlichem Software-Neustart. Ungültiger
Vergleichshash in der installierten API abgewiesen, Inhalt/Revision unverändert.
Bestehender Syncthing indexiert sowohl die eingehende synthetische Note als auch
von der App erzeugtes Memory; Verfügbarkeit jeweils auf verbundenem Peer bestätigt.
Globaler Vault-Chat und explizites `Merke dir:` mit echtem lokalen Modell bestanden.
Echte Webrecherche und Chat-Websuche liefern Quellen; ohne öffentliche Freigabe 403,
exakter Suchtext und Idempotenz bestätigt, kein Cloud-Modellaufruf in M2.

Erweiterte verschlüsselte Off-VM-Sicherung und isolierter Restore bestanden:
Schema 0011, 40 Originaldateihashes, sechs Memory-Dateien inklusive Archiv,
Provider-Masterkey und neue SSH-Identitäten/Units; private Schlüssel passen zu
öffentlichen Identitäten. Fehlender Mount erhält den restaurierten PG-Index;
simulierter Transportfehler nach echten Reads rollt Änderungen zurück. Diese
Ausfalltests liefen auf der isolierten Kopie; der produktive Mount wurde nicht
unterbrochen. Vorhandene Proxmox-Konfiguration unverändert. Private Belege liegen
unter `.local/deployment/`, keine Runtime-Daten oder Secrets in Git.

HTTPS für ausdrücklich freigegebenes 192.168.18.0/24 auf Port 443 ergänzt, bisherige
Netze erhalten, Rollbackkopie gesichert. Vom WorkMac erneut zertifikatsgeprüft HTTP
200 für Startseite und Health. Direkte TLS-Browserprüfung durch URL-Richtlinie
verweigert; kein Umweg. Lange Vollabgleiche serialisieren Memorywrites; 1.556
Notizen wurden in einem separaten vollständigen Dateilesetest in 68,559 s gelesen.
Das ist kein End-to-End-API-Latenzversprechen oder eine Produktionsreifeerklärung.

M3 vollständig beauftragt; erstes lokales Gateway jetzt in Entwicklung, siehe oben. Lesend
bestätigt: vorhandenes n8n 2.7.5 läuft, Health 200, API ohne eigenen Schlüssel 401.
Keine alten Credentials übernommen; neue konkrete Integrationszugriffe separat
freigeben. M3/M4/M5 und deren Akzeptanzfälle bleiben offen.

## Historische M2-Checkpoints

Implementiert: Projekträume, scoped Quellenchat, unveränderte gehashte Originale,
asynchrone Extraktion, Office-/PDF-/Text-/Tabellen-/Bildformate, Fundstellen, lokale OCR,
strukturierte Decimal-Tabellenprüfung, öffentliche SearXNG-Recherche und gezielter
allowlistgeschützter HTML-Abruf. Oberfläche für Projekte/Uploads/Suche/Quellen und
Memory mit Herkunft, Revisionen und Konfliktvergleich; kanonisches Markdown,
read-only Allgemeinvault, begrenzte Memorywrites, Tombstones und Crash-Reconciliation.
Direktes `Merke dir:` ist source-/revisiongebunden und idempotent, ohne Modellwrite.

Finaler Codecheckpoint `da6b671`: CI 37269020685 vollständig grün, 91 Tests
einschließlich PostgreSQL-Migration Upgrade/Downgrade/Upgrade und Queue-Recovery.
Lokal 90 bestanden, ein PostgreSQL-Test separat in CI. Browserprüfungen mit
synthetischen Daten: Projekte, Mehrfachupload, Fundstellen, Decimal, Quellenchat,
Memoryrevisionen sowie öffentliche Chat-Webfreigabe; mobile UI ohne Überlauf.
Typen/Lint, Secret-Scans und reproduzierbarer Containerbuild bestanden.

Eigene VM installiert `da6b671`, Schema `0011`, beide APIs gesund. Echte isolierte
Dateipipeline bestanden: neun Formate einschließlich Scan-PDF/Bild-OCR, Original-
downloads mit SHA-Abgleich, CSV/XLSX-Decimal-Summen, PDF-Fundstelle und Projekt-
isolation. Echtes unverändertes Mac-mini-Modell nennt 37 EUR mit source.pdf/Seite 1.
Parser ohne Netzwerk, ohne Vault/Secrets, nonroot und read-only Root; Landlock
verweigert andere Quelldateien und Systemdateien. Separate Quellenworker erhalten
Chatpriorität. Keine realen OpenRouter-Aufrufe oder zusätzlichen Cloudkosten in M2.

Verschlüsselte Sicherung vom 05.10.2026 außerhalb der VM kopiert und SHA-geprüft.
Isolierter DB-Restore: Schema 0011, 31 Gespräche/58 Nachrichten, alle 40 gesicherten
Originale gegen gespeicherte SHA-Werte geprüft; gesicherter Masterkey entschlüsselt
das bestehende Providersecret. Keine Klartextdump-Datei, Wiederherstellungsschlüssel
bleibt auf dem WorkMac. Temporäre Restore-DB entfernt. Vorhandene Proxmox-
Konfiguration gegen Baseline unverändert; Rückfallimage/Konfigurationskopie erhalten.
Private Belege bleiben im ignorierten `.local/deployment/`.

Der hier zunächst offene vorhandene Vault-/Search-Zugang und die A09-/Restore-
Abnahme wurden am 05.10.2026 abgeschlossen; aktuelle Nachweise stehen oben.
Die folgenden Checkpoints dokumentieren den jeweiligen früheren Prüfstand.

Aktueller Codecheckpoint `c9ce59a`: CI 37275069080 grün, lokal 93 Tests bestanden
und PostgreSQL separat in CI. Der Index verwirft verlorene/ersetzte Mounts und
Transportfehler; passende globale Notizen werden vor dem 500-Einträge-Limit gefiltert.
SSHFS-Cache deaktiviert, fsync für Datei/Verzeichnis am echten Mount akzeptiert.
Eigene VM auf `c9ce59a` aktualisiert; beide API-Endpunkte gesund. Laufzeitkonfiguration
bindet den begrenzten Vault und Suchrelay ein, Parser weiterhin ohne Vaultvolume.
Vorherige Konfigurationen unter `/etc/obdaai/rollback-m2-c9ce59a` gesichert.
Die abschließende Diagnose benutzte versehentlich `Settings()` statt `from_env()`;
ihre fehlgeschlagene Assertion ist daher kein Nachweis eines Mountfehlers.
Eine korrigierte Laufzeit- und API-Prüfung steht noch aus. Weitere Remote-Aufrufe
wurden von der automatischen Freigabeprüfung wegen Modellkapazität nicht ausgeführt,
ohne Sicherheitsentscheidung. Keine erneute Zugriffsfreigabe benötigt.

## Zugriffsfreigabeprüfung 05.10.2026

Auf „weitermachen“ wurde die Einrichtung der zuvor konkret beschriebenen Zugänge
vorbereitet. Die automatische Freigabeprüfung lehnte den ersten Mutationsaufruf ab:
die Antwort sei für SSHFS-Installation, Dienstkonten und neue Zugriffsschlüssel nicht
ausdrücklich genug. Der Aufruf wurde nicht ausgeführt; keine neuen Zugänge aktiviert.
Eine konkrete gebündelte Zustimmung wurde abgefragt. Unabhängig davon sind die
reviewbaren SSH-/Compose-Vorlagen und Live-Abnahme-/Rückfallkriterien unter
deploy/access/ vorbereitet. Noch keine bestehende Vault-/Such- oder Sync-Konfiguration
geändert. Nach expliziter Freigabe aktuelle Rechte/Mounts nochmals prüfen und die
geprüfte Einrichtung vornehmen; erst nach echter M2-Abnahme M3 implementieren.

Der Benutzer hat die konkret gebündelte Einrichtung anschließend ausdrücklich mit
„Ja, genau diese begrenzte Einrichtung ist erlaubt“ freigegeben. Eigene VM: SSHFS
und zwei neue Identitäten eingerichtet. Server: begrenzte SFTP-/Forwarding-Konten,
readonly Vault-Bindmount, ausschließlich Memory writable und .obsidian maskiert;
SSH-Konfiguration geprüft/neugeladen, bestehender Sync aktiv. Neue Units verbinden
sich; ein synthetischer Filetest bestätigt read/write/rename und Sperre außerhalb
Memory. Die App-Anbindung und vollständige Live-Abnahme laufen noch. Vor Indexierung
wird PostgreSQL-/Dateisperrung für parallele API-/Worker-Abgleiche getestet; Backups
erhalten neue Zugangsunits/Identitäten und den kanonischen Memory-Bereich.

## Live-Abnahme und Erreichbarkeit 05.10.2026

Designcommit `8e0eb11` gepusht, CI 37275715883 grün und auf der eigenen VM
installiert; helle/dunkle/mobile Blautöne in synthetischer UI visuell geprüft,
Styles über beide echten API-Endpunkte bestätigt. Keine Funktionsänderung.

Vorheriger Prüfstand `9645f94` (CI 37276615918 grün): descriptorbasierter begrenzter
Vault-Lesepfad, ohne Symlinkfollowing. 30 echte Notizen: 8,267 s vorher, 2,381 s
nachher. Lokal 94 Tests bestanden; echte Mountattestation und begrenzter Search-
SSH-Zugang geprüft (anderer Port und Shell verweigert). Vorhandener Syncthing-
Dienst aktiv, kanonischer Vault konfiguriert und lokale Sync-API erreichbar.
Echte App-Webrecherche bestanden: zehn Treffer, exakter öffentlicher Suchtext,
ohne Freigabe HTTP 403 und identische Anfrage-ID ohne erneute Recherche.

Vault-Gesamtabnahme weiter offen: Inhaltsduplikate verursachen wiederholte
Remote-Pfadprüfungen bei Renameerkennung (bis 95 gleiche Notizen). `552bfa8`
begrenzt das gesamte Inventar und benutzt dessen Pfadmenge; lokal 95 Tests
bestanden, PostgreSQL separat in grüner CI 37277172434. Dieser Stand wurde anschließend installiert und durch weitere Optimierungen ersetzt.
Vollständige Vault-Abnahme siehe aktuelle Nachweise unten.

HTTPS-Meldung des Benutzers bestätigt: beide APIs healthy, VM-lokales HTTPS
zertifikatsgeprüft HTTP 200. Mac routet über en7 / 192.168.18.248, VM empfängt
TCP SYN von genau dieser Adresse und verweigert sie gemäß bisheriger Allowlist
(192.168.117.0/24, 172.17.50.0/24). Konkrete Ergänzung nur dieses Clients /32
für HTTPS vorbereitet. Benutzer hat ausdrücklich stattdessen das gesamte Netz
192.168.18.0/24 freigegeben. Auf eigener VM ergänzt, bisherige Konfiguration unter
/etc/obdaai/rollback-https-network-19216818024 gesichert. Vom WorkMac aus
zertifikatsgeprüfte Startseite und Healthcheck erneut HTTP 200; keine andere
Netzfreigabe geändert. Browser-Tool verweigert die direkte Seitenprüfung gemäß
URL-Richtlinie; kein Umweg verwendet.

Weitere echte M2-Abnahme: eigene synthetische Note unter bestehender Sync-UID
angelegt, lokaler Syncthing-Index und Verfügbarkeit auf verbundenem Peer bestätigt.
Globaler Wissenschat mit echtem lokalem Modell bestanden, ausschließlich diese
synthetische Note im Kontext. Explizites `Merke dir:` kanonisch und idempotent.
Belege: ignorierte m2-syncthing-live.json / m2-memory-chat-live.json.

Die automatische Freigabeprüfung verweigerte vorübergehendes Stoppen des
Quellenworkers für den Test; nicht ausgeführt und nicht umgangen. Tests liefen
stattdessen mit normaler Serialisierung. Vollständige Scan-/Writeabnahme bleibt
offen, weil lang laufende Hintergrundscans die Schreibfreigabe verzögern.
`c252b05` verwendet pro Ordner verankerte Deskriptoren für Geschwisterdateien:
30 echte Notizen 2,928 → 0,744 s. Lokal 96 Tests bestanden, CI 37278911672 grün.
Dieser Stand wurde installiert; keine andere Dienstunterbrechung für Abnahmen
genehmigt/ausgeführt. Erweitertes Backup-/Restore-
Skript für neue Schlüssel/Units/Memory vorbereitet; noch keine neue Restore-Abnahme.

Aktuell installiert `502e1c2`, CI 37280251178 grün. Begrenzte, verankerte
Verzeichniskette statt wiederholter Ancestor-Öffnungen: 1.556 echte Notizen,
Inventar und vollständige Lektüre in 68,559 Sekunden, keine Lesefehler. Das ist
ein Dateilesetest; die vollständige API-/DB-Abnahme läuft gesondert.

Neue Editor-Korrektur: HTTP-409 lädt die aktuelle Fassung zum ausdrücklichen
Vergleich und behält den Entwurf. Normales Speichern bleibt während des Vergleichs
gesperrt. Eine Übernahme prüft den verglichenen Hash auch nach bereits erfolgtem
Hintergrundabgleich. Synthetischer mobiler Browsercheck: externe Änderung ->
Sync -> veralteter Editor abgelehnt -> Entwurf erhalten -> Vergleich -> ausdrücklich
bestätigte Übernahme, Revision 6. Gezielter Einzelnotizabruf nach HTTP 409
verifiziert; der Vergleich ist unabhängig von der 100-Treffer-Listenbegrenzung. Screenshot nur lokale Fixture. Backend lokal
98 Tests bestanden, ein PostgreSQL-Test für CI; Ruff/mypy und Frontendbuild grün.
Diese Editor-Korrektur ist noch nicht auf der VM installiert.

## M3-Folgeauftrag 05.10.2026

Der Benutzer beauftragt alle M3-Funktionen nach Etablierung sämtlicher M2-Funktionen.
Konkrete Reihenfolge, A08/A10-A12-Abnahme, Integrationsvorbedingungen und aktuelle
Primärquellen sind in docs/m3-plan.md vorbereitet. M3-Code ist noch nicht implementiert.
Die Reihenfolge bleibt M2-Abschluss → M3. Die begrenzte Vault-/Suchzugangsfreigabe
liegt inzwischen ausdrücklich vor und ist eingerichtet. Keine automatischen
Produktivworkflows oder Home-Assistant-Änderungen aktiviert. Nächster Schritt:
echte M2-Abnahme und erweiterten Restore abschließen, anschließend M3 umsetzen.

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


## Neue M3-Vertikale: lokale Aufgabenanalyse

Fester letzter ai.analyze-Schritt implementiert: ausdrückliche Quellen- und
vertraute Skillbindungen, ausschließlich lokaler Provider ohne Laden von
Cloud-Secrets, gespeicherter vollständiger Prompt und Modell-/Providerrevision.
Teilantworten bleiben bei Fehler/Abbruch erhalten; durabler Claim und getrennte
PG-Session-Sperre verhindern doppelte Inferenz. Recovery eines laufenden Claims
stoppt ohne zweiten Modellaufruf. Zwölf neue API-/Modelltests und ein separater
PG-Sperrentest. Lokal insgesamt 179 bestanden, fünf PG-Tests für CI. Browser-Fixture
bestätigt erfolgreichen Modellschritt und 390px ohne horizontalen Überlauf.
Der alte synthetische Chatprovider sperrte zuerst den neuen Schritt; nach gezielter
Fixture-Ergänzung erfolgreicher neuer expliziter Lauf. Commit d1413d3: CI
37295615837 grün, 184 Tests einschließlich fünf echter PostgreSQL-Prüfungen.
Auf eigener VM installiert; beide APIs und zertifikatsgeprüftes HTTPS gesund.
Echte lokale Modellabnahme mit zwei Skillrevisionen bestanden: deutsche und
englische Antworten, Provider-/Skillrevisionen und Idempotenz geprüft; Testaufgabe
pausiert, Skill deaktiviert, keine Cloudaufrufe. Verschlüsselter Off-VM-Backup
und isolierter Restore auf Schema 0014 bestanden: zwei Modellbelege, vier
Taskrevisionen, fünf Skillrevisionen, drei Aktionsbelege, 40 Originalhashes,
sechs Memory-Dateien und begrenzte Zugangsschlüssel erhalten. Weitere M3-Funktionen offen.


## Usability-Überarbeitung auf Benutzerfeedback

Neue Projekte werden über einen getrennten leeren Dialog angelegt; danach öffnet
sich der Projektraum mit Dokumentenablage für PDF, DOCX, XLSX und PPTX.
Archivierte Projekte sind standardmäßig verborgen. Bestehende Projekte können
weiter bearbeitet werden. Aufgaben werden über einen Dialog mit Name, Ziel, Art,
Projekt, ausdrücklicher Dokument- und Skillauswahl angelegt; keine JSON-Eingabe.
Ansichten für aktuelle, historische und archivierte Aufgaben, gespeicherte Ergebnisse.
Natürlicher Zieltext kann lokal einen Titelentwurf erzeugen; kein Speichern/Start
oder neue Rechte durch das Modell, strikte JSON-Validierung nur im Backend.
Chat-Modus AUTO / Nur lokal sichtbar wählbar. Nur lokal erzwingt LOCAL_ONLY auch
in einem cloudfreigegebenen Gespräch und dessen Retry; externe Websuche abgewiesen.
AUTO bleibt innerhalb vorhandener Freigaben. Modellverbindungen mit Basisfeldern
und getrennten erweiterten Grenzen; Einstellungen erklären Darstellung, Chat,
Verhaltensregeln und tatsächlichen Integrationsstand. Werkzeuge erklären Zweck
und verfügbare Aktionen. Zeitpläne, wiederkehrende Ausführung und MCP-Verwaltung
sind noch nicht verfügbar und werden ausdrücklich als offen angezeigt.

Synthetische Browserabnahme: neues leeres Projekt, Dokumentenablage, Aufgabenformular
Speichern/Aktivieren/Ausführen, Ergebnis nach Reload erhalten, finale Pause;
390px Formular und Chat ohne horizontalen Überlauf. 18 eindeutig zugeordnete
M2/M3-Abnahmeprojekte auf eigener VM wiederherstellbar archiviert; andere Projekte,
Quellen-IDs und Originalhashes unverändert.

Verhaltensregeln (Skills) ebenfalls mit Formular und getrenntem Prüfen/Aktivieren;
technisches portables Format nur unter Erweitert. Synthetischer Browsercheck
bestätigt zwei Stichwörter, gespeicherten Text und deaktivierte erste Revision.
CI de87b5f fand mehrdeutige Beschriftung am Aufgaben-Projektfeld; explizite
Beschriftungen in 763cf82 korrigiert, dessen Browserprüfung bestanden.

Einstellungen in fünf Bereiche gegliedert: Allgemein, Modelle, Antwortverhalten,
Verbindungen, Datenschutz. Antwortverhalten enthält dieselben echten Skillformulare.
Darstellung und Standardmodus für neue Gespräche werden im Browser gespeichert;
situative Chatwahl bleibt getrennt. Standardmodus nach Reload und neuer
Gesprächsanlage im Browser geprüft; Testpräferenz danach auf AUTO zurückgesetzt.
Modellverbindungsdialog mit Basisfeldern und zugeklappten erweiterten Grenzen geprüft.

Usability-Quellstand `6c77532`: CI 37298796667 vollständig grün, 194 Tests mit fünf
PostgreSQL-Prüfungen, erweiterte Browserabläufe, Container und Secret-Prüfung.
Auf eigener VM installiert, Schema 0014, beide APIs gesund, blaue Hell-/Dunkelassets.
Zertifikatsgeprüfte angemeldete HTTPS-Abnahme bestanden: neue Formularassets,
eigenes Test Projekt erhalten, genau 18 bekannte Abnahmeprojekte archiviert;
realer lokaler Titelentwurf speichert/startet nichts; echte lokale Chatantwort
bei Nur-lokal-Override trotz Gesprächs-Cloudfreigabe, null Cloudaufrufe.
Synthetisches Gespräch anschließend archiviert. Zwei durch Abnahmebelege bekannte
Testaufgaben wiederherstellbar archiviert, übrige Aufgaben unverändert.
Neue verschlüsselte Off-VM-Sicherung und isolierter Restore auf Schema 0014
bestanden: 40 Originalhashes, sechs Memory-Dateien, Modell-/Task-/Skill-/Aktionsaudit,
begrenzte Zugangsschlüssel und Units erhalten; bestehende Proxmox-Konfigurationen
unverändert. Arbeitsverzeichnis sauber nach Dokumentationscommit.
Benutzer möchte aktuell keinen MCP-Server anbinden, sondern die Möglichkeit für
später. Ausführbare n8n-Zeitplanung mit einmaligen/wiederkehrenden Terminen und
Termin-/Ergebnisübersicht bleibt nächster M3-Funktionsschritt; M3 bleibt Teilstand.

### Zeitplanung: installiert und mit echtem n8n-Takt abgenommen

Migration 0015 und normale Terminwahl für manuell/einmalig/täglich/wöchentlich
implementiert. Zeitpläne bleiben getrennt von unveränderten TaskSpec-Manifesten;
Aufgaben-, Quellen- und Skillrevisionen werden vor Einreihung und beim Worker erneut
geprüft. Planänderungen besitzen unveränderliche Revisionen, Ausführungen eigene
Terminbelege mit Link zu Ergebnissen. Pause stoppt auch bereits eingereihte
Zeitplanläufe am Worker-Boundary, ohne manuelle Läufe derselben Aufgabe zu sperren.
DST, Duplikate, Parallelität, verpasste Termine, Review bei Drift und ein enger
Maschinenzugang nur für leere Zeitimpulse sind getestet. Die GUI bietet Filter für
geplante, wiederkehrende, pausierte und bisher ausgeführte Aufgaben; Uhrzeitänderung
und persistente Wochentage sind im synthetischen Browser tatsächlich geprüft.

Nach ausdrücklicher Freigabe wurden genau zwei eigene n8n-Credentials und ein
eigener aktiver Minutentakt-Workflow eingerichtet. Er sendet ausschließlich leere
Zeitimpulse an die feste eigene HTTPS-API, keine Aufgabeninhalte oder Dokumente.
TLS bleibt verifiziert, Redirects deaktiviert. Der neue Maschinenzugang ist nur für
`/api/scheduler/tick` gültig. Bestehende n8n-Workflowversionen und Aktivierungszustände
sind unverändert; keine fremden Container- oder Firewalländerungen.

Echte Live-Abnahme: einmalige, tägliche und wöchentliche lokale Leseaufgaben mit
genau einem dauerhaft gespeicherten Ergebnis, korrekten Folgeterminen und Pause vor
dem nächsten tatsächlichen n8n-Takt bestanden. Eine zeitgesteuerte lokale KI-Aufgabe
beantwortete die synthetische Frage korrekt; keine privaten Quellen und keine
Cloudaufrufe. Testaufgaben anschließend wiederherstellbar archiviert, übrige Aufgaben
unverändert. Ergebnisse und Terminbelege nach eigenem API-/Worker-Neustart sowie
nach finalem Rollout erhalten. Einstellungen zeigen echten Clock-Status/letzten Takt.

Installiert: `95329de`, Schema 0015, beide APIs gesund; angemeldete HTTPS-Abnahme
mit Zertifikatsprüfung bestanden. CI 37304161168 vollständig grün: 204 Tests inklusive
sechs echten PostgreSQL-Checks, Browser, Container und Secrets. Verschlüsselte
Off-VM-Sicherung und isolierter Schema-0015-Restore bestanden: fünf Zeitpläne,
17 Planrevisionen, vier Terminbelege, drei lokale Modellbelege, 40 Originalhashes,
sechs Memory-Dateien sowie begrenzte Zugänge und Scheduler-Konfiguration erhalten.
Temporäre Restore-Datenbank entfernt, bestehende Proxmox-Konfiguration unverändert.

M3 bleibt teilweise: externe MCP-/REST-/Browser-Ausführung, Reconciliation und
produktive Home-Assistant-Wartungsaktionen sind weiterhin offen. Der Aktionsgateway
bleibt pausiert. Bei folgenden eigenen Compose-Rollouts muss die zusätzliche
`scheduler.compose.yaml` eingebunden bleiben; siehe `docs/schedules.md`.

### Home Assistant: feste lesende Wartungsübersicht

Optionaler `ha.inspect`-Adapter implementiert: ausschließlich GET config/states an
den festen HA-Host, direkte Verbindung zur vom Operator freigegebenen IPv4 mit
festem Host/TLS-SNI, Zertifikatsprüfung, keine Redirects/Proxies/Parameter. Nur
Version, gemeldeter Installationstyp, Supervisor-/Backup-Präsenz und Update-Einträge
bleiben im LOCAL_ONLY-Beleg. Keine anderen Gerätezustände, Ortsdaten, Release-URLs
oder fremden Anweisungen im Bericht/Modellkontext. Keine HA-Schreiboperation vorhanden.
Der bereitgestellte Token kann breitere Rechte haben; der Adapter bietet sie nicht an.

Echter Adapter-Lesecheck vom autorisierten Operator-Rechner bestanden: TLS geprüft,
Version 2026.9.3, 55 Update-Einträge, zwei als verfügbar gemeldet, null Schreibaufrufe.
Supervisor-/Backup-Präsenz gelten ausdrücklich nicht als geprüfte Installation oder
erfolgreicher Restore. UI zeigt verständlichen Bericht mit dauerhaftem Beleg und
gesperrter Wartung. Synthetischer unabhängiger Browsertest: Bericht erzeugt, nach
Reload erhalten, keine HA-Verbindung aus Fixture. Die neue lesende VM-Anbindung
ist bis zur ausdrücklichen eigenen Egress-/Tokenmount-Freigabe nicht aktiviert.

Tests behandeln Auth/CSRF, unbekannte Parameter, erlaubte Zielgrenzen, Host/TLS-SNI,
Redirects, Fehler/Größenlimits, minimierte Ausgabe und Belegreplay ohne zweiten
Aufruf. Ergänzte CI prüft die mobile Berichtsansicht und Persistenz. M3 bleibt
Teilstand; produktive Wartungsänderungen und Restore-Abnahme sind weiterhin offen.
Lokal 214 Tests bestanden, sechs PostgreSQL-Checks separat für CI; Ruff/mypy,
Frontendbuild und Secret-Scan bestanden. Siehe `docs/home-assistant.md`.

HA-Lesequelle `75c7f04`: CI 37306828415 vollständig grün (Python/PostgreSQL,
Browser samt mobilem Bericht/Reload, Container und Secrets). Das eigene VM-Image
ist gebaut; laufende Installation bleibt 95329de, bis die angefragte eigene
Tokenmount-/HA-Egress-Freigabe vorliegt. Kein HA-Write, kein neuer n8n-Workflow
und keine Firewalländerung in diesem Schritt durchgeführt.

### HA-Leseanbindung installiert und live abgenommen

Nach ausdrücklicher Freigabe: `75c7f04` auf eigener VM installiert, Schema 0015,
beide APIs gesund. HA-Token ausschließlich in API/API-HTTPS schreibgeschützt gemountet;
keine Worker-/Parser-Mounts. Exakt eine genehmigte ausgehende HA-TCP-443-Regel ergänzt;
alle bisherigen Regeln bytegleich erhalten, persistente eigene Konfiguration geprüft,
Rollback mit vorheriger Release-/Egress-/Backup-Konfiguration und DB gesichert.
Die eigene RemainAfterExit-Egress-Unit hat beim Start keine Regeln neu angewendet;
der gestoppte Rollout wurde nach Statusprüfung durch gezieltes Einfügen der einzigen
neuen Regel fortgesetzt. Keine Bestandsdienst- oder HA-Konfigurationsänderung.

Echte angemeldete HTTPS-Abnahme auf eigener VM bestanden: feste HA-Abfrage erfolgreich,
Version 2026.9.3 / 55 Update-Einträge / zwei verfügbar. Dauerhafter Beleg, identischer
Belegreplay ohne erneuten HA-Aufruf, sonstige Aktionen/Aufgaben unverändert. Neuer
Oberflächenbundle verifiziert, n8n-Clock gesund, alle vier bisherigen automatisch
ausgeführten Ergebnisse und Terminbelege erhalten. Schreibgateway weiterhin pausiert.

Neue verschlüsselte Off-VM-Sicherung und isolierter Schema-0015-Restore bestanden:
HA-Lesebeleg unverändert wiederhergestellt, HA-Token/Overlay/genaue Netzwerkfreigabe
vorhanden; fünf Zeitpläne, 17 Planrevisionen, vier Terminbelege, drei lokale Modellbelege,
40 Originalhashes und sechs Memory-Dateien erhalten. Temporäre Restore-Datenbank
anschließend entfernt; bestehende Proxmox-Konfiguration unverändert. Dies ist ein
obdaAI-Restore und keine HA-Restore-Abnahme. Produktive HA-Wartungsaktionen bleiben
offen und gesperrt; M3 bleibt Teilstand. CI der installierten Quelle: 37306828415
vollständig grün, 220 Tests inklusive sechs echten PostgreSQL-Checks.

### MCP-Verwaltung für künftige Verbindungen

Normale Einstellungsdialoge für Name, Adresse, Protokoll und optionale verschlüsselte
Bearer-Tokens. Entwürfe ohne Netzwerkaufruf, Änderungen revisionsgebunden,
Archivieren/Wiederherstellen. Begrenzte Katalogprüfung für exakt serverseitig
freigegebene Ziele; Remote-Metadaten erteilen keine Werkzeugrechte. Aktuelles
stateless MCP sowie zwei Legacy-Versionen, JSON/Request-SSE, feste IP/TLS-SNI,
keine Redirects/Proxies, Größen-/Zeit-/Paginationgrenzen. Schema 0016.

Lokal 241 Tests bestanden, sieben PostgreSQL-Fälle für CI. Ruff/mypy und
Frontendprüfung bestanden; echte synthetische HTTP-Verbindung im Browser mit
Reload und Wiederherstellung geprüft. Realer MCP-Server aktuell nicht gewünscht;
Produktionsallowlist bleibt leer. OAuth, stdio und entfernte Ausführung offen.

Weitere reine HA-Backup-/Supervisor-GETs antworten mit HTTP 401. Dies belegt eine
Zugangsgrenze, keine Aussage über vorhandene Backups. Keine HA-Schreibaktionen
oder Änderung fremder Dienste durchgeführt; HA-Restore-Abnahme weiterhin offen.

### Chat → normaler Aufgabendialog

Eigene Nachricht über „Als Aufgabe planen“ mit unverändertem Ziel und optionalem
Projekt in den Dialog übernehmen. Keine geerbten Dokument-/Skill-/Cloudfreigaben,
keine automatische Planung oder Ausführung. Titel, Dokumente und Termine normal
auswählen; Speichern bleibt pausiert. Lange Nachrichten werden nicht abgeschnitten.
Browserabnahme prüft Zielgleichheit und gesperrten Start der gespeicherten Aufgabe.
Dies ersetzt noch keine generische Chat-zu-n8n-Workflowgenerierung.

### Home Assistant: Installation und Sicherungsmetadaten

Die HTTP-401-Bestandsnotiz wurde geklärt: Core 2026.9.3 erlaubt diese Supervisor-
HTTP-Pfade nicht. Der vorhandene Zugang funktioniert mit den vorgesehenen festen
WebSocket-Lesewegen. Echte Operator-Abnahme: HA OS 18.3, Core 2026.9.3,
Supervisor 2026.09.3 gesund/unterstützt, 61 Backups, Dienst idle, null Agentfehler,
letzte laut HA abgeschlossene automatische Sicherung 03.10.2026. Kein HA-Write.

Eigener read-only Werkzeugadapter und normale Berichtsansicht ergänzt. Feste
TLS/IP/Kommandogrenzen, minimierte Ausgabe, keine Download-/Key-/Restorefunktion,
keine Modellübergabe. Tests behandeln Handshake-/ID-/Schemafehler, Größenlimit,
Zielgrenzen, Zertifikatsprüfung, Geheimnisreduktion und dauerhaftes Replay. Die
Sicherungsexistenz gilt weiterhin nicht als Restore-Abnahme; Wartung bleibt gesperrt.

Chatübernahme wird über den bestehenden Editor übernommen und beim Verlassen
der Aufgabenansicht verworfen; die vorherige CI-Lifecycle-Abnahme war fehlgeschlagen.
Die reparierte gemeinsame Quelle muss vor Installation wieder vollständig grün sein.

Die instrumentierte Browserdiagnose zeigte den Dialog samt übernommenem Ziel
bereits korrekt an. Ursache der bisherigen CI-Fehler war der zusammengesetzte
Labeltext eines initial befüllten Textarea. Ein expliziter zugänglicher Feldname
wurde ergänzt; der Test behält exakte Zielgleichheit und deaktivierten Start bei.

### M3: echte aufgabenbezogene n8n-Vorlage in Entwicklung

Neue feste Webhook → Gateway-Vorlage (2.7.5, Webhook 2.1 / HTTP Request 4.4).
Chat-Aufgaben können eine revisionierte Bindung vorbereiten; Task-Center ergänzt
getrennte Einrichtung, Veröffentlichung, Freigabe und Aufruf samt n8n-Execution-ID.
Neue Schema-0017-Tabellen: WorkflowBinding und WorkflowDispatch. Keine privaten
Aufgabeninhalte in n8n, kein zusätzlicher Zeitplan. Externe Einrichtung und
Veröffentlichung gehen durch das Aktionsgateway mit persistiertem Intent vor I/O,
Pause/Widerruf/Expiry-Prüfung pro POST und Abgleich statt blindem Retry.

Unklare Credential-Erstellung stoppt; Workflowerstellung über Namen/exakten Graph
abgleichen; Veröffentlichung über exakte aktive Version. Vor Start und Callback
Remoteversion prüfen, dann atomare PG-Queue/Laufbindung. Lokale Tests bestanden;
PG-/Browser-/reale n8n-Abnahme und Installation noch ausstehend. Aktuell live bleibt
6eeba62/Schema 0016. Siehe docs/task-workflows.md. M3 noch nicht abgeschlossen.

### 2026-10-05: n8n-Vorlage installiert, MCP-Lesevertikale geprüft

Quelle 940d601 mit Schema 0017 auf eigener obdaAI-VM installiert. Beide APIs gesund;
alte Compose-Overlays und Firewall unverändert. Neue n8n-Key-Mounts nur readonly an
API/API-HTTPS. Synthetische Vorlage wurde eingerichtet/veröffentlicht, echter
Callback mit Execution-ID 276 führte zu erfolgreichem lokalen PostgreSQL-TaskRun.
Testaufgabe archiviert, eigener Testworkflow deaktiviert, globale Schreibpause
wiederhergestellt. Ein zusätzlicher n8n-Historienabruf lieferte keinen Beleg, weil
saveDataSuccessExecution=none ausdrücklich gesetzt ist; dauerhafte App-Belege
sind der Nachweis. Erweiterter Backup/Restore für Schema 0017 steht noch aus.

MCP-Lesewerkzeuge: eigener serverseitiger URL/Name/Schema-Digest, keine Parameter,
aktueller Katalog und Verbindungsrevision, Textlimits, kein Modellkontext. 290 lokale
Tests bestanden, acht echte PostgreSQL-Tests lokal übersprungen (CI erforderlich).
Ruff, mypy, Frontend-Build und Quell-Secret-Scan grün. Synthetischer echter HTTP-Aufruf
über UI plus Reload zeigt gespeicherten Ergebnisbeleg. Keine realen MCP-Ziele
angefordert oder auf der VM freigegeben. Produktionsrollout dieser Ergänzung und
CI noch ausstehend. M3 insgesamt weiterhin offen: Browservertikale, weitere
API-/MCP-Operationen, HA-Wartung mit verifiziertem Wiederherstellungsweg und
vollständige Abnahme/Restore.

### 2026-10-05: weitere M3-Lesevertikalen und Restore 0017

Erweiterter verschlüsselter Backup/Restore nach konkreter Freigabe bestanden:
Schema 0017, ein Workflowbinding/Dispatch samt erfolgreichem TaskRun und
entschlüsselbarem begrenztem Callbacktoken, 40 Originalhashes, sechs Memory-Dateien,
Provider-/Zugangsschlüssel, Revisionen und Belege erhalten. Produktiv-HA und die
produktive obdaAI-Datenbank wurden nicht restauriert. Bestehende Proxmox-Konfiguration
unverändert. Nachweis privat workflow-backup-acceptance.json.

MCP-Quelle 5bc9b7d gepusht, CI 37337995133 vollständig grün. Auf VM weiterhin
940d601 (Schema 0017), neuer Rollout ausstehend.

Passive Browserprüfung implementiert: feste HTTPS-Ziele/Digest/IPv4, begrenzter
HTML-Abruf, Offline-Chromium, geschütztes PNG und dauerhafte Belege. Echter eigener
VM-Container-Test nach engem Seccomp-chroot-Fix bestanden: Chromium-Sandbox an,
non-root, readonly, keine Capabilities/Ports/Secrets/Netzwerk; Script, Metadata-Bild
und Datei-Frame blockiert. Kein bestehender Dienst umgebaut. Testcontainer gestoppt.
Vorheriger unveränderter Seccomp-Test scheiterte sichtbar an Chromiums Sandbox-
chroot; Sandbox wurde nicht abgeschaltet. Produktionsziele weiterhin leer; neue
Browser-Compose-Konfiguration noch nicht installiert. Keine interaktive Browser-
oder Login-/2FA-Automation behauptet.

Home Assistant: fester Wartungsplan zeigt konkrete Versionen, Backupmetadaten und
fehlende Wiederherstellungsvoraussetzungen. Drei lesende HA-Aufgabentypen im
normalen Dialog mit Terminen/Ergebnissen ergänzt. Keine Eingabe von Entitäten,
URLs oder Service-Payloads. Kein impliziter LLM-Kontexttransfer. UI-Abnahme mit
synthetischer HA-Aufgabe und gespeichertem Wartungsbericht bestanden; Worker-
Anbindung auf VM und echte Task-Abnahme noch ausstehend. Produktive HA-Writes und
autonome Wartung bleiben ohne verifizierten Restore gesperrt.

310 lokale Tests bestanden, acht echte PostgreSQL-Tests lokal übersprungen.
Ruff, mypy, TypeScript, UI-Build und Quell-Secret-Scan grün. Neue CI ergänzt
synthetische Browseroberfläche und echten netzwerkfreien Chromium-Container.
M3 weiterhin Teilstand; nächster Schritt CI, reviewed own-VM rollout, echte
HA-Berichtsaufgabe und Chat-Tool-/Task-Integration, danach restliche M3-Abnahmen.

### 2026-10-05: Chat-Systemberichte und natürliche Aufgabenentwürfe

Feste lesende System-/HA-Berichte über lokalen Router im Chat integriert, mit
ActionReceipt und LOCAL_ONLY-Antwortkontext. Keine Modellargumente, keine Writes,
kein impliziter Cloudtransfer. Aufgabenentwürfe wählen jetzt auch feste HA-
Berichtstypen; Speicherung, Termin und Aktivierung bleiben im normalen Dialog.
321 lokale Tests bestanden, acht PG-Tests lokal übersprungen; Ruff/mypy und
Secret-Scan grün. UI synthetisch geprüft. Quelle vor Rollout; M3 noch offen.

### 2026-10-05: M3-Leseergänzungen live abgenommen

b50cbd1/Schema 0017 installiert; CI 37341712365 in allen fünf Bereichen grün.
Eigener Browserdienst non-root, readonly, cap-drop ALL, kein Netzwerk/Port/Secret;
synthetischer Job im installierten Dienst erfolgreich (PNG 12.825 Bytes, Script
nicht ausgeführt). API/API-HTTPS gesund; HA-Key am eigenen Worker nur readonly,
bestehende übrige Overlays und Firewall unverändert; MCP-/Browserziele leer.

Reale HA-Wartungsbericht-Aufgabe über PostgreSQL-Worker erfolgreich:
Task dea28a3d-c41a-4b29-89bc-28e79cca4852, Run a3de0b23-d1f4-4824-8539-693889b446ec.
HA 2026.9.3, 61 gemeldete Backups, keine Änderungen, keine Cloud, Kosten null.
Testaufgabe pausiert/archiviert. Realer lokaler Router wählte ha.inspect; Chat-Run
755e85f3-2097-4ff9-9587-5fe1fa450aa1 mit dauerhaftem ActionReceipt und LOCAL_ONLY
Antwort erfolgreich; eigenes Gespräch archiviert. Globale Schreibpause erhalten.

Erneuter verschlüsselter Off-VM-Backup und isolierter Restore nach Rollout bestanden:
Schema 0017, Workflowbelege/Schlüssel, neue Browser-/HA-Konfiguration, 40 Original-
hashes, sechs Memory-Dateien. Keine produktive DB-/HA-Wiederherstellung.

Echte UI-Abnahme zeigte, dass Ergebnisse/Workflowdetails hinter dem offenen
Aufgabendialog lagen. Korrigiert: bei geöffnetem Dialog stehen beide darin, nach
Schließen weiterhin in der Übersicht. Regression prüft Bericht und bedienbaren
Laufmanifest-Klappbereich innerhalb des Dialogs. UI-/CI-/Rollout der Korrektur folgt.
M3-Lücken explizit in docs/m3-acceptance-status.md; keine vollständige Abnahme behauptet.

### 2026-10-05: Dialogfix live, Planungsübergang erweitert

8c59f62 installiert, CI 37342938561 in allen fünf Jobs grün. APIs gesund,
Schema 0017 unverändert; Overlays/Firewall/Browsercode identisch. Ergebnis- und
Workflowbereiche im offenen Aufgabendialog bedienbar; lokal per UI geprüft.

Nächste Ergänzung: Task-/Workflow-Chatklassifikationen geben einen klaren Weg über
„Als Aufgabe planen“ statt eines technischen Meilensteinfehlers. Neue Entwürfe
können Aufgabenart und ausdrückliche HH:MM-/Wochentag-/ISO-Datum-Vorgaben vorschlagen.
Keine Speicherung, Aktivierung, Workflow-/HA-Aktion oder Berechtigung im Entwurf.
Explizite Zeit/Tag-/Vergangenheitsprüfung zusätzlich zum bestehenden Zeitzonen-/DST-
Validator; manuelle TaskSpec bleibt getrennt von Zeitplanvorschlag. UI-Abnahme zeigt
HA-Wartungsbericht / Samstag / 02:00, ohne Aufgabe anzulegen. n8n-Details in eigener
erweiterter Auswahl verborgen. 329 lokale Tests bestanden, acht PG-Tests lokal
übersprungen; Ruff/mypy/TS/Build/Secret-Scan grün. CI und Rollout dieser Ergänzung folgen.

### 2026-10-05: echte Entwurfsabnahme erkennt Wochentagfehler

cd9e7d2 installiert; CI 37343904014 vollständig grün. Echte lokale Entwurfsabnahme
wurde sicher mit 422 abgewiesen: Modell lieferte Samstag als ISO-6, Plan erwartet
Montag=0/Samstag=5. Keine Aufgabe oder Zeitplan angelegt/aktiviert. Diagnose nur mit
synthetischem Ziel, ohne Cloud oder HA-Eingriff. Prompt ergänzt explizite deutsche/
englische Zuordnung aller sieben Tage sowie vollständiges verschachteltes JSON-
Beispiel. Isolierter Testprozess mit dem echten lokalen Modell liefert nun Samstag=5
und gültigen HA-Wartungsbericht-Entwurf. Regression für falsches Samstag=6 abgewiesen.
19 Entwurfstests grün; CI und erneute Abnahme des installierten Endpoints folgen.

### 2026-10-05: finaler M3-Lesestand und Entwurf live geprüft

9dbee1f installiert; CI 37344908607 mit allen fünf Jobs vollständig grün.
Beide APIs gesund, Schema 0017, Overlays/Firewall/Browsercode unverändert.
Echte installierte Entwurfs-API nach Korrektur bestanden: ha.maintenance.plan,
weekly, Europe/Berlin, 02:00, Samstag=5. Manuelle TaskSpec; keine Speicherung,
Aktivierung, Ausführung oder Cloud. Privater Beleg plan-draft-live.json.

Reale mobile UI zeigt gespeicherten erfolgreichen HA-Bericht und offene Restore-
Voraussetzungen innerhalb des Dialogs; n8n-Details separat aufgeklappt. Nachweis
privat live-ha-task-dialog.png. Eigene lokale Testserver/Abnahmetabs beendet.
Produktiver Hub bleibt unter https://192.168.117.103/ erreichbar.

Für HA-Wartung fehlt der Wiederherstellungsschlüssel-/Integritäts-/Restore-Nachweis;
Ablageort des Schlüssels wurde abgefragt, kein Schlüssel im Chat angefordert.
Weitere noch nicht implementierte Funktionen stehen unverändert im M3-Abnahmestand:
interaktive Browseranmeldung/2FA, allgemeine freigegebene Workflowgraphen und weitere
externe Operationen, Task-Writes/Autonomieprofile. M3 ist nicht vollständig fertig.
Diese Dokumentationsänderung ändert den installierten Code 9dbee1f nicht.

### 2026-10-05: Task-Center erholt sich nach vorübergehendem API-Ausfall

Native Live-Prüfung nach Rollout zeigte einen dauerhaft stehenbleibenden JSON-
Parsefehler einer HTML-Proxyantwort. Gemeinsamer JSON-Parser meldet jetzt lesbar
vorübergehende Nichtverfügbarkeit oder unbestätigte Schreibaktion. Task-Center
aktualisiert Listen, Zeitimpuls, Läufe und Termine gemeinsam; nur erfolgreiche
Hintergrundabfrage löscht deren eigene Fehlermeldung. Formfehler bleiben separat.
Keine automatische Wiederholung von Writes. Browserabnahme simuliert HTML-503,
prüft Erholung und eine unbestätigte POST-Aktion mit erhaltenem Entwurf.

CI 37346718646 für 1aa2c6e vollständig grün: 338 Python-Tests inklusive PostgreSQL,
Ruff/mypy (42 Module), TS/Build, mobiler Browsercheck mit HTML-503/Erholung und
unbestätigtem POST, echter Chromium-Smoke, Container und Secrets.
1aa2c6e auf eigener VM installiert: beide APIs gesund, Schema 0017, Overlays,
Firewall und Browsercode unverändert. Native Live-UI zeigt n8n verbunden und
gespeicherten erfolgreichen HA-Wartungsbericht ohne alten Parsefehler. Screenshot
privat live-ha-task-dialog-1aa2c6e.png.

Abschließender, ausdrücklich erlaubter verschlüsselter Off-VM-Backup/temporärer
Restore für installierten Stand 1aa2c6e erneut bestanden: snapshot-20261005T171713.524650853Z,
Schema 0017, Workflow-/Task-/Aktionsbelege und Schlüssel, 40 Originalhashes,
sechs Memory-Dateien. Temporäre DB entfernt, produktive DB/HA unverändert.
Privater Beleg m3-read-backup-acceptance.json. Gemessener kombinierter Backup-/
isolierter Prüfablauf 73.6 Sekunden; dies ist keine vollständige Server- oder HA-RTO.

Diese abschließende Dokumentation ändert den installierten Code 1aa2c6e nicht.
M3 verbleibt teilweise umgesetzt; offene Funktionen in docs/m3-acceptance-status.md.

### 2026-10-05: dauerhafte Aufgabenfreigaben und begrenzte Schreibprofile

Schema 0018 ergänzt verbrauchbare Aufgabenfreigaben, unveränderliche Freigabe-
Ereignisse und Aktions-/Run-Verknüpfung. Nur analysieren bleibt Standard. Für genau
eine wiederherstellbare Projektarchivierung gibt es confirm_each und bounded_autonomous.
Einzelfreigaben warten dauerhaft ohne Workerjob; n8n/Termine umgehen sie nicht.
Begrenzte Freigaben gelten für konkrete Vorgaben-, Steuerungs- und Policyrevision
bis zum Ablauf, maximal ein Write. Widerruf, Projekt-/Task-/Skill-/Policy-Drift,
Aktionspause und doppelte Zustellung werden am finalen gemeinsamen Gateway geprüft.
Direkte Gateway-Ausführung einer aufgabenbezogenen Aktion wird abgewiesen.

Lokaler Effekt, Freigabeverbrauch, Aktionsbeleg und Teilschritt werden gemeinsam
committet; ein Timeout nach dem Effekt rollt die gesamte lokale Änderung zurück.
Task-Center zeigt Profile, konkrete Ziele, Ablauf, Widerruf und Historie ohne
JSON-Eingabe. Natural-language-Entwürfe bleiben rechtefrei. Neue Queue-/mobile
Browserabnahme verwendet ausschließlich eigene synthetische Projekte. HA-Writes
bleiben gesperrt. CI und Live-Rollout folgen nach lokalen Checks.

### 2026-10-05: M4-Dateirenderer und isolierte Vorschauen begonnen

Strikte reine Datenpläne erzeugen echte editierbare DOCX/PPTX, PDF-Seitenauswahlen
und Bildzuschnitte/Collagen. Vor jeder Verarbeitung werden die gebundenen
Originalhashes geprüft; vorhandene Ausgabeversionen bleiben unverändert. Kein
Modellcode, Cloudaufruf, beliebiger Dateipfad oder URL-Download. Synthetische DOCX
und beide PPTX-Folien mit LibreOffice/Poppler gerendert und visuell geprüft.

Separater nonroot Offline-Runner mit Landlock pro Auftrag, CPU-/Datei-/Zeitlimits,
ohne Netzwerk, DB, Secrets oder Vault vorbereitet. Neue Linux-Containerabnahme
prüft vier Formate, sechs Vorschauseiten und doppelte Zustellung. Ihr Ergebnis
steht noch aus; produktiver Runner noch nicht installiert. API, dauerhafte
Anwendungsversionen, Projekt-/Chat-Dialog und lokale Modellplanung sind noch offen
(docs/m4-acceptance-status.md). M4 ist ausdrücklich noch nicht fertig.

Lokale Gesamtprüfung dieses Standes: 360 passed, neun PostgreSQL-Integrationsfälle
ohne lokale Fixture übersprungen; Ruff und mypy (47 Module) sowie Source-Secretscan
erfolgreich. Aufgabenprofil-CI 37368721985: Browser und Chromium-Smoke erfolgreich;
Python/Container/Secrets warten noch auf GitHub-Runner. Daher bisher kein Rollout
der Aufgabenprofile auf die produktive VM.

### 2026-10-05: lokale Dateientwürfe, Folgeänderungen und Chatübernahme

Zusätzlich zum Quellstand f1194a2: Schema 0020 bewahrt authentifizierte lokale
Modellherkunft und Chatantwort-Snapshots pro Datei. Normale Word-/PowerPoint-
Entwurfsdialoge, genaue Folienanzahl, explizite Quellenauszüge und serverseitige
Fundstellen; keine Cloud und keine Rechte durch Modelloutput. Folgeentwürfe nutzen
den alten Datenplan und benötigen dessen genaue Revision. Direkte Chatantwort-
Übernahme als Word mit serverseitigem Gespräch-/Projekt-/Revisionscheck.
Synthetische API-/mobile UI-Abnahme einschließlich aller vier Dateiarten bestanden.
377 lokale Tests bestanden, zehn PG-Fälle ohne Fixture übersprungen.

Eigenes App- und Offline-Image f1194a2 gebaut; vier echte Linux-Dateien/sechs
Vorschauen erfolgreich. Artefakt-PG-Fall selbst erfolgreich; Gesamtcheck erkannte
zwei zusätzliche periodische Wartungsjobs in der gemeinsamen Testqueue. Der eigene
Artefaktworker erhält nun keine periodische Registrierung; Wartung verbleibt beim
bestehenden Worker. Korrigierter Gesamtcheck, CI und Rollout folgen. Produktiv
bleibt 1aa2c6e/0017. Keine M3/M4/M5-Vollabnahme behauptet.

## Live-Abnahme: Upload-Verarbeitung vom Vault trennen

Der gemeinsame Source-/Vault-Worker kann neue Uploads hinter langen SSHFS-Abgleichen
zurückhalten. Eigene getrennte Queue-Consumer für Uploads und Vault; der synchrone
Vault-Scan läuft mit eigener DB-Transaktion in einem Thread, damit Heartbeats weiter
arbeiten. Mount, vorhandener Sync und Rechte bleiben erhalten. Native Anbietertests
sind ein separater Entwicklungsschritt und derzeit nicht im produktiven Router aktiv.

### Live-Regressionsfund: unabhängige Speicher-Locks

Der Artefaktquota-Lock hatte versehentlich die bestehende Memory-ID 791103043
wiederverwendet. Ein langer Vault-Scan konnte damit ein neues Dateiprojekt blockieren;
die synchrone DB-Warteoperation im async API-Handler verzögerte weitere HTTP-Anfragen.
Artefakte erhalten die eigene registrierte Lock-ID 791103047. Die Dateitransaktion
läuft in einem Thread mit eigener Session; der API-Ereignisloop bleibt responsiv.
Regressionen prüfen Health während wartender Dateitransaktion und zwei unabhängig
gehaltene echte PG-Locks. Live-Timeouts sind erfasst; Dateiabnahme wird wiederholt.

## M5: direkte Anbieter in normaler Oberfläche vorbereitet

Schema 0021 bindet neue Cloudgespräche an OpenRouter, OpenAI oder Anthropic; alte
Freigaben bleiben OpenRouter. Native textbasierte Adapter, verschlüsselte Schlüssel,
separate Serverallowlist, geprüfte befristete Preise, Reservierung und unterscheidbare
Usage-Schätzung implementiert. Native Einrichtung mobil, feste Endpunkte und
serverseitig gesperrte Tests im synthetischen Browser geprüft. Synthetischer API-
Gesamtablauf belegt private lokale Antwort, native Freigabe, konkrete Reservierung,
Stream und Kostenaudit. Kein echter nativer Zugang und keine neue Egress-Freigabe.

400 lokale Tests bestanden; zehn PG-Fälle separat auf eigener VM bestanden. Ruff/
mypy (52 Module), TS/Build, Source-Scan und drei Browserchecks bestanden. Schema 0021
und Native-Oberfläche noch nicht produktiv ausgerollt. Native-Live-Abnahme bleibt
zugangsabhängig; M3/M4/M5 nicht vollständig. Details: docs/native-provider-status.md.

### Verschlüsselter Artefakt-Restore und reale Downloads

Eigene Live-Dateipipeline `9b6f30b` erzeugt vier Formate / sechs Vorschauseiten.
Word/PDF/Bild visuell geprüft und authentifizierte HTTPS-Downloads mit Ausgabehash
verifiziert. PPTX wartet auf Font-Folgeprüfung. Lokaler Modell-Entwurf antwortet
noch mit 422; nur synthetische Diagnose, keine ungeprüfte Dateierstellung.

Snapshot `snapshot-20261005T215303.639568315Z`: verschlüsselt auf bestehendem privaten
Mac-Backup-Pfad, isolierter Restore Schema 0020 bestanden. Acht Artefaktrevisionen mit
Spec-, Ausgabe- und Vorschauhashes sowie 42 Originalhashes, sechs Memory-Dateien,
Masterkey/Providersecret, SSH-Schlüssel/Units, bestehende Task-/Workflowbelege geprüft.
Temporäre Restore-DB entfernt; produktive DB und HA unverändert. Kein HA-Restore
und kein voller Server-RTO-Nachweis. HTTPS antwortet wieder zertifikatsgeprüft vom Mac.
