# Architektur und Entscheidungen

## Modularer Monolith

```mermaid
flowchart LR
  Client[MacBook / iPhone Browser] --> API[FastAPI + statische React UI]
  API --> PG[(PostgreSQL: App-Rolle)]
  API --> Router[Lokaler Router + finaler Privacy-Gateway]
  Router --> Local[Mac mini: OpenAI-kompatible Inference]
  Router --> Cloud[Explizit erlaubter Cloud-Adapter]
  PG --> Worker[Worker: gleiche Codebasis / Procrastinate]
  Worker --> Runner[Isolierter Dokument- / Browserrunner]
  API --> Catalog[Policy-geschützter Werkzeugkatalog]
  Catalog --> Systems[Explizit erlaubte MCP / REST Systeme]
  API --> N8N[n8n: einzige Zeitplan- / Workflowengine]
  N8N --> API
  Worker --> Vault[Vorhandener serverseitiger Obsidian-Vault]
```

Keine generischen Agents als eigene Dienste, kein Next.js-Server, kein Redis,
kein neuer Inference-Gateway und kein zweiter Cron. Procrastinate ist eine etablierte
PostgreSQL-Queue für App-Jobs, keine zusätzliche Workflowengine. Periodische
Procrastinate-Jobs beschränken sich auf interne Memory-Indexpflege; wiederkehrende
Benutzeraufgaben terminiert weiterhin n8n. Es entsteht keine zweite Benutzer-Zeitplanengine.
Die optionale lokale Memory-Vektorsuche speichert begrenzte JSON-Vektoren in derselben
App-Datenbank; pgvector ist nicht erforderlich und wird nicht installiert.
React wird von FastAPI statisch ausgeliefert; Chat-SSE bleibt im App-Pfad.

## Kritische Vereinfachungen
- Vorhandenes n8n zunächst nur inventarisieren und über dokumentierte API anbinden.
  Keine parallele neue Instanz. Migration auf die Ziel-VM ist vor M5 zu entscheiden,
  damit dort auch Hintergrundprozesse laufen; bestehende Workflows bleiben erhalten.
- Syncthing bleibt alleiniger Vault-Sync. Kein neuer Sync-Dienst. App-Reconciliation
  verwaltet nur Dateien/Revisionen im autorisierten Memory-Bereich.
- Deterministische lokale Artefaktbearbeitung von generativer Bildarbeit trennen.
- Standardschnittstellen nicht als Nachweis von Tool-/Schemaunterstützung behandeln.
- V1 beginnt mit LOCAL_ONLY. Frühere Plattform-Cloudfreigaben werden nicht übernommen.

## Ressourcen / Deploymententscheidung
Ziel: separate stabile Debian-13-Linux-VM gegenüber dem Inference-Mac. Ob die
vorhandene ai-core-VM zusätzlich oder eine neue dedizierte VM verwendet wird, ist
noch zur Auswahl offen; keine neue VM wird allein aus dem Begriff separat abgeleitet. Startannahme: 4 vCPU, 8 GiB RAM, 80 GiB Datenträger,
ein Batchjob und eine lokale Inference gleichzeitig. Kein GPU-Bedarf. Diese Werte
sind noch nicht gemessen; M5 misst Chatlatenz, Runner-Spitzen und parallele Jobs.
Bestehende ai-core-Dienste sind Rückfallbetrieb und keine automatische
Installationsfreigabe. Bei Wiederverwendung bleiben ihre Ports/Netze/Volumes unverändert.
Proxmox-Kapazität und neue VM-ID/Adresse vor Provisionierung prüfen und freigeben.
App und n8n haben getrennte DBs, Rollen, Schlüssel und Migrationen. n8n bekommt
keinen direkten App-DB-Zugriff. Runner erhält weder Providersecrets noch Docker-Socket.

## Modellunabhängiges Gedächtnis — Ausbau vom 21.10.2026

Das Gedächtnis gehört der Anwendung. `Memory` und `MemoryRevision` bleiben der
gemeinsame Speichervertrag; der vorhandene PostgreSQL-/SQLAlchemy-Pfad wird
erweitert, keine zweite Memory-Datenbank eingeführt. `storage="vault"` bezeichnet
unveränderte kanonische Markdown-Notizen im bestehenden Obsidian-Vault.
`storage="app"` bezeichnet native Einträge ohne Vault-Abhängigkeit. Der vorhandene
Profil-Singleton bleibt ein eigener, manuell gepflegter Kontext mit feldweiser
Cloudfreigabe. Automatisches Lernen kopiert oder überschreibt ihn nicht. Auch
manuell gewählte typisierte Antwortpräferenzen behalten ihre Autorität; eine
gelernte Stilvorliebe wird nicht zur gleichrangigen Systemvorgabe.

### Lebenszyklus, Herkunft und Berechtigungen

Native Einträge enthalten Kategorie, Faktentyp, Status, Revision/Hash,
Gültigkeitszeitraum, Herkunft und einzelne freigegebene Provider. Persönliche,
Projekt-, Gesprächs- und Präferenzerinnerungen bleiben unterscheidbar. Eine Aussage
über einen Plan oder eine Hypothese ersetzt keinen bestätigten Fakt.
Inhaltsduplikate mit abweichendem Faktentyp oder anderen Freigaben erzeugen einen
Bearbeitungskonflikt; sie übernehmen keine früheren Cloudrechte. Eindeutige
Korrekturen können frühere Werte derselben Faktengruppe ersetzen. Mehrdeutige
Widersprüche bleiben Vorschläge zur Prüfung.

Gelernte Inhalte benötigen wörtliche eigene Nutzeraussagen. Nachrichten-ID,
Revision, Gespräch und Hash werden vor und nach der lokalen Verarbeitung erneut
geprüft. Besonders sensible Vorschläge speichern zunächst ausschließlich Pointer,
Quote-Offsets und feste Metadaten: kein zweiter persistierter Rohtext im
Vorschlagsspeicher. Vorschau und Freigabe rekonstruieren den Text aus der noch
aktuellen Quelle. Geänderte, deaktivierte oder archivierte Quellen erlauben keine
Übernahme. Quelleninhalte und Erinnerungen bleiben unvertrauenswürdiger Kontext,
keine Systemanweisungen oder zusätzlichen Werkzeugrechte.

Private Erinnerung ist der Standard. Eine Cloudfreigabe ist an den konkret
ausgewählten Provider und die aktuelle Revision gebunden. Der normale Auto-Modus
erteilt diese Freigabe nicht. Die finale Kontextprojektion prüft Eigentümer,
Scope, Quelle, Gültigkeit, Settings und Revision erneut am Providerübergang;
Änderungen während der Verarbeitung werden berücksichtigt. Gesprächsauszüge bleiben
`LOCAL_ONLY`. Relevantes privates Gedächtnis hält eine Auto-Antwort lokal;
explizites Cloud lässt nicht freigegebene Erinnerungen aus. Memorytexte fließen
nicht implizit in öffentliche Suchanfragen ein.

Explizites Vergessen nativer Einträge entfernt deren Text, Memory-Versionstexte
und Embeddingderivate. Zusammenfassungen werden invalidiert; Quellenpointer und
ein Einweg-Hash verhindern das erneute Lernen aus der alten Quelle. Die Original-
nachricht sowie bereits gespeicherte Chatantworten, historische Run-Snapshots,
Vault-Originale und externe Sicherungen werden dadurch nicht vollständig gelöscht.
Vault-Löschungen behalten ihren bisherigen wiederherstellbaren Archivvertrag.
Vergessen ist deshalb keine Zusage eines systemweiten rückwirkenden Datenpurges.

### Lernen und Kontextauswahl

`memory_settings.py` bietet revisionierte Einstellungen; die Oberfläche wählt ein
aktiviertes lokales Lernmodell unabhängig vom Antwortmodell. Lernen und Nutzung
sind separat schaltbar, alle Vorschläge können optional vorab geprüft werden.
Sensitive Prüfung lässt sich nicht abschalten. Der billige Aufnahmefilter lehnt
gewöhnliche Fragen, Begrüßungen, zitierte Dokumente und hypothetische Beispiele
vor einer Inferenz ab. Der konservative direkte Aussagefilter ist keine allgemeine
semantische Extraktion beliebiger Gesprächsinhalte. E-Mail-/Archivbelege und
Modellantworten werden nicht automatisch zu persönlichen Fakten.

`memory_learning.py` prüft vor dem Modellaufruf eine kleine geschlossene Grammatik
vollständiger eigener Familienaussagen: Name, Alter und Reitfähigkeit einer Tochter
oder eines Sohns. Hinzu kommen vollständige eigene Berufsangaben nach
„Ich arbeite [jetzt|inzwischen] als …“ mit begrenzten Rollenwörtern; Pläne,
Qualifikationen, Fragen und zusammengesetzte Aussagen werden nicht so gedeutet.
Reitdauer unterstützt Ziffern und deutsche Zahlwörter von eins
bis zwölf. Nur exakt passende vollständige Aussagen werden deterministisch als
wörtlich belegte Fakten verarbeitet; Fragen, unsichere Formulierungen und fremde
Quellen erhalten dadurch keine Sonderfreigabe. Diese strukturelle Prüfung ist
ein eigener Aufnahmeweg und keine nachträgliche Erhöhung einer Modellkonfidenz.
Eine belegte aktuelle explizite Vault-Speicherung derselben Nachricht verhindert
ein zusätzliches automatisches App-Memory. Dafür werden Server-Ursprung, Scope,
Revision/Inhalt und die kanonische Datei geprüft.
Andere zugelassene Aussagen verwenden den konfigurierten begrenzten lokalen
JSON-Schema-Aufruf; jedes Ergebnis wird zusätzlich gegen den unveränderten
Originaltext geprüft. Sensible Prüfung, Quellenbindung und Privacy gelten für
beide Wege unverändert. Der
bestehende Procrastinate-Worker verarbeitet die Jobs nachrangig; der Chat wartet
nicht auf diesen separaten Modellaufruf. Durable Jobs besitzen einen Queued-only-
Claim, Einstellungen-/Quellenbindung und keine blinden Wiederholungen nach
unsicherer Ausführung. Fehlendes lokales Modell erzeugt keine erfundenen Fakten
und keinen Cloudfallback. SQLite dient weiterhin Entwicklung und Vertragstests.

`memory_retrieval.py` ergänzt den vorhandenen RAG-/`ContextPart`-Pfad um strukturierte
Felder, lexikalische Relevanz und optional lokale Vektorähnlichkeit. Die Auswahl ist
auf höchstens 2.000 Kandidaten begrenzt; Scope, aktive Revision und Gültigkeit
werden zusätzlich geprüft. Konfigurierbare Mengen- und Kontextbudgets werden durch
die tatsächliche Chat-/Modellkapazität weiter begrenzt. Bei fehlender oder
fehlerhafter Embeddingkonfiguration bleibt der strukturierte/lexikalische Pfad
verfügbar. Vektoren sind abgeleiteter Cache mit Memory-Revision, Inhalts-Hash und
Modell-/Konfigurationsbindung, keine weitere Wissensquelle.

Interne periodische Indexpflege (`hub.memory-index`) verarbeitet höchstens 20
fehlende oder veraltete Einträge pro Minute, einschließlich manueller Änderungen.
Sie verwendet die bestehende nachrangige Memory-Queue und einen Queueing-Lock;
sie installiert weder einen eigenen Dienst noch eine neue Datenbank oder pgvector.

`memory_summary.py` erzeugt unabhängig von einer erfolgreichen Faktenextraktion
lokale **extraktive Gesprächsauszüge**. Bei mindestens zwölf aktiven Nachrichten
wird ein Fenster von höchstens 100 Nachrichten betrachtet; die neuesten acht
bleiben der aktuellen Gesprächshistorie vorbehalten. Ältere Ausschnitte besitzen
Quellenpointer, Revisions-/Hashprüfung und einen begrenzten Umfang. Entscheidungen
und Pläne können priorisiert werden, bleiben aber als unvollständige wörtliche
Auszüge gekennzeichnet. Das ist weder eine vollständige Langzeitrekonstruktion
noch eine neue Faktenbestätigung.

### Migration und Abnahmegrenze

Migration `0046_intelligent_memory.py` ist additiv: zusätzliche Metadaten an
`memories`, sowie Settings, Pointer-Vorschläge, Lernjobs, Embeddings und
Gesprächsauszüge in derselben Datenbank. Altbestand erhält `vault`/`owner`/`active`
als Standardwerte; bestehende Inhalte, Profilangaben, Revisionen und Privacy-Labels
werden nicht neu geschrieben. Ein Downgrade verweigert das Entfernen bei nativen
Erinnerungen oder vorhandenen neuen Zustandsdaten. Vor einem Rollout bleiben
aktuelle Sicherung und Prüfung des konkreten Zielstands erforderlich; eine
erfolgreiche additive Migration oder Sicherung ist kein Wiederherstellungsnachweis.

Der exakte Patch `aa4a5ae` bestand 2707 lokale Tests und die
vollständige CI (2701 bestanden, 6 übersprungen). Die erste Migration
unter 2c85335 führte 0046 ein; der neue Patch erhielt dieses Schema und vorhandene
native/abgeleitete Zustände ohne erneute Migration. Die erste HTTP-Abnahme unter
2c85335 bestand initiales Modell-Lernen und Abruf, scheiterte aber an der leeren
LLM-Berufskorrektur. Ihr Fehlerbeleg bleibt erhalten. Die neue getrennte Prüfung
belegt den engen Berufsparser im HTTP-/PostgreSQL-Workerweg, späteren Abruf,
Korrekturlebenszyklus und ein echtes lokales Antwortmodell; sie ist keine neue
LLM-Extraktionsabnahme der Korrektur. Allgemeine Sprach-/Langzeitqualität und
reale optionale Embeddings bleiben offen. Den verbindlichen Umfang führt STATUS.

### Gedächtnis konfigurieren und betreiben

`GET /api/memory-settings` liefert die aktuelle vollständige Konfiguration mit
`revision`. `PUT /api/memory-settings` übernimmt dieselbe Struktur mit der zuvor
angezeigten Revision (CAS); bei HTTP 409 aktuellen Stand neu laden und den eigenen
Entwurf vergleichen. `enabled` steuert die Nutzung, `extraction_enabled` das Lernen.
Im `config`-Objekt steuern `review_required`, `learn_from_projects`,
`max_memories`, `max_context_chars`, `min_confidence` und `summary_enabled` die
begrenzten Abläufe. `sensitive_review_required` bleibt serverseitig eingeschaltet.
`extractor_provider_id` ist die ID eines aktivierten bestehenden lokalen Modells;
`null` verwendet das lokale Standardmodell. Sensible Prüfung bleibt verbindlich.
Das UI zeigt verständliche Modellnamen statt technischer IDs. Der gewöhnliche
Memory-Abruf besitzt zusätzlich eine Obergrenze von **2.400 UTF-8-Bytes**; Modell-
und Chatbudget können tatsächlich verwendete Anzahl und Textumfang weiter senken.
Ein höherer Einstellwert ist deshalb keine Zusage entsprechend großen Kontexts.

`GET/POST /api/memories`, `GET/PATCH/DELETE /api/memories/{id}` und
`GET /api/memories/{id}/versions` verwalten vorhandene native oder Vault-Einträge.
Native Erstellung wählt ausdrücklich `storage="app"`; der alte API-Standard
bleibt `vault`. Änderungen/Löschungen benötigen die aktuelle Revision.
`GET /api/memory-candidates` zeigt quellengebundene Vorschläge;
`POST /api/memory-candidates/{id}/review` benötigt `expected_revision` und
`decision="approve"` oder `"reject"`. Geänderte Quellen werden nicht übernommen.
Alle schreibenden Aufrufe benötigen die bestehende Anmeldung, Origin- und
CSRF-Prüfung; Erinnerungen verleihen keine Werkzeuge oder weiteren Rechte.

Optionale Embeddings werden ausschließlich serverseitig eingerichtet:
`HUB_MEMORY_EMBEDDING_BASE_URL`, `HUB_MEMORY_EMBEDDING_MODEL` und optional
`HUB_MEMORY_EMBEDDING_KEY_FILE`. Die Basisadresse muss exakt einer freigegebenen
lokalen `/v1`-Adresse in `HUB_LOCAL_ENDPOINTS_JSON` entsprechen; deren festgelegte
IP wird am Transport geprüft. HTTPS-/Netzwerkfreigaben werden nicht automatisch
erweitert. Erst `config.embedding_enabled=true` aktiviert diesen Pfad. Die
bestehende interne Indexpflege verarbeitet höchstens 20 fehlende/veraltete
Einträge je Minute. Modell oder Konfigurationsfingerprint ändern die Cachebindung;
veraltete Vektoren werden nicht als aktuelle Belege verwendet und können begrenzt
neu aufgebaut werden. Ohne erreichbaren passenden Dienst bleibt Textsuche
verfügbar. **Für diese Lieferung wurde kein Embeddingdienst installiert oder
konfiguriert und keine reale Embedding-Abnahme behauptet.**

Die vorhandene nachrangige Memory-Queue verarbeitet Lernen und Indexpflege.
Lernjobstatus und feste Fehlerkategorien trennen fehlendes Modell, veränderte
Quelle, Widerruf und unterbrochene Arbeit. Diagnose verwendet Status/Metadaten;
keine vertraulichen Quelltexte, Tokens oder Providerfehler als öffentliche Logs
weiterreichen. Unsichere oder unterbrochene Ausführung nicht blind wiederholen.
Die Prüfung von Aufnahme, Aktualisierung und Abbruchrechten bleibt am finalen
Speicher-/Providerübergang verbindlich.

Vor Updates PostgreSQL einschließlich Queue-/Memorytabellen, kanonischen Vault,
Konfiguration und erforderliche Schlüssel geschützt sichern. Schlüssel getrennt
und sicher verwahren; weder Sicherungen noch Inhalte gehören in Git. Ein Backup
ist kein bestätigter Restore. Der 0046-Downgrade besitzt Verlustschutz und darf
bei nativen Erinnerungen oder neuen Zustandsdaten nicht erzwungen werden.
**App-only-Rollback auf den früheren Vault-Code ist bei vorhandenen
`storage="app"`-Zeilen unsicher**: alte Reconciliation versteht diese Speicherart
nicht. Writer stoppen, Daten erhalten und eine geprüfte kompatible Recovery
vorbereiten; keine nativen Zeilen löschen, keinen destruktiven Downgrade und
keine ungeprüfte Datenbankwiederherstellung durchführen, um Rollback zu erzwingen.
