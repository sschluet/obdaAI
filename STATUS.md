# obdaAI — Status 05.10.2026

## M3 in Entwicklung · Aktionsgateway, Chat-Skills und manuelle Aufgaben

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
