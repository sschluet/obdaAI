# Gemeinsamer Anfrage-, Kontext- und Ausführungsvertrag

## Ausgangspunkt und Grenzen

Die Bestandsaufnahme vom 22.11.2026 fand keine fehlende Plattformbasis, sondern
auseinanderlaufende Verträge: Routing, Toolauswahl und Abschlussprüfung verstanden
ähnliche Prompts unterschiedlich; Modellwartezeit und Antwortstillstand hatten
keine getrennten Grenzen. Entwurfsschutz, Memory-Faktidentität und Aufgaben-Kontext
waren ebenfalls uneinheitlich. FastAPI, React, PostgreSQL, bestehende Provider,
RAG, Integrationen und dauerhafte Ausführungsbelege bleiben erhalten.

Diese Lieferung erweitert die vorhandenen Komponenten. Sie ist keine Aussage,
dass beliebige Administration oder jeder natürliche Prompt zuverlässig arbeitet.
Eine erfolgreiche Verbindung, ein passendes JSON-Schema und eine erfolgreiche
Modellantwort sind unterschiedliche Nachweise.

## Anfrage und Werkzeuge

`agent_intent.py` definiert einen versionierten, inerten `RequestIntent` mit
Zielen, Beobachtungs-/Änderungsmodus, Forschungsbedarf und erforderlichen Belegen.
Enge bekannte Standardfragen können ohne Modell klassifiziert werden. Unbekannte
Formulierungen erhalten eine lokale semantische Interpretation mit demselben
Vertrag. Der vollständige Ausgabeauftrag steht auch im Prompt, damit die
Einordnung nicht allein von der Schemafunktion eines Servers abhängt. Herkunft
und Vertragsversion setzt die Anwendung. Unbekannte Ziele, unvollständige oder
ungültige Anforderungen werden abgelehnt.

Das Interpretationsmodell sieht die aktuelle Frage sowie ID, Typ und Namen der
aktuell zulässigen Verbindungen. Es erhält keine Zugangsdaten und kann keine
Rechte vergeben. Die Anwendung prüft aktuelle Profil- und Regelrevisionen erneut.
Interpretationsfehler gewähren keine zusätzliche Autorität. Bei fehlgeschlagener
notwendiger Einordnung wird die Anfrage nicht still an einen gewöhnlichen Chat
weitergereicht; der Entwurf bleibt zum erneuten Versuch erhalten. Die Laufzeitdiagnose
zeigt eine beeinträchtigte Auftragseinordnung getrennt von der Erreichbarkeit.
Ein weiterhin unbekannter Bezug zu privaten Zielsystemen wird ausdrücklich als
unklar gemeldet. Er wird nicht still an einen gewöhnlichen Chat weitergereicht.

Die Toolgrammatik verwendet die effektiven Rechte des jeweiligen Auftrags.
Reine Beobachtungsaufträge bieten keine Shell-, Versand-, Upload- oder
HTTP-Schreiboperationen an. Die letzte Dispatch-Prüfung bleibt zusätzlich erhalten. HA-Pfadgrammatiken
verwenden ein positives Pfadmuster statt eines vom lokalen Compiler abgelehnten
Lookaheads. Webhooks bleiben in der Generierung und unabhängig davon am
Ausführungsrand gesperrt.
Gemischte Aufträge bleiben an einzelne Ziele, deren Schritt-/Effekt-/Zeitgrenzen
und die menschlich konfigurierten Freigaben gebunden. Die globale Obergrenze
ersetzt keine Zielgrenze. Ein in einem gemischten Auftrag nur beobachtetes Ziel
erhält ausschließlich Leseoperationen; Änderungen verlangen ein eigenes
`effect_postcondition` für genau dieses Ziel. Diese Einschränkung gilt auch vor
dem vorbereiteten Schritt und unmittelbar vor dem tatsächlichen Versand.

Erfolg erfordert zur Frage passende erfolgreiche Beobachtungen. Eine
API-Startseite oder Konfigurationsantwort belegt keine Lampenliste.
`document_content` verlangt einen tatsächlichen Inhaltsabruf statt Suchmetadaten.
Eine Inhaltsfolgefrage kann aus genau einem weiterhin gültigen, zuvor gezeigten
Dokument eine konkrete Leseauswahl erhalten; mehrere Treffer werden nicht
willkürlich ausgewählt. Nach einem
fehlgeschlagenen Zugriff muss eine alternative Schnittstelle tatsächlich den
fehlenden Beleg liefern. Nicht belegte Ergebnisse bleiben als solche erkennbar.
Der explizite Antworttyp `document_inventory` gilt nur für eine lesende
Metadatenübersicht eines einzelnen Paperless-Ziels. Erst beim belegten Abschluss
ersetzt die Anwendung freie Modellprosa durch tatsächlich beobachtete IDs, Titel,
Trefferzahlen und Seitengrenzen. Werkzeug- und Seitenplanung bleiben beim Agenten;
Inhaltsanalyse und mehrere Ziele werden dadurch nicht als erledigt behandelt.

Bekannte Folgefragen verwenden aktuelle validierte Quellen auch bei mehreren
aktivierten Verbindungen. Generische Belegansichten werden nach tatsächlichem
JSON-Encoding und UTF-8-Byteumfang begrenzt; vollständige Originalbelege und
Hashes bleiben unverändert gespeichert. Eine belegte leere Mailauswahl ist von
fehlender Quelle verschieden: Eine ausdrückliche Rückfrage zu dieser Auswahl
benötigt keinen neuen Posteingangs-/Gesendet-Scan. Sie beweist keine allgemeine
Aussage über beantwortete oder unbeantwortete Mails im übrigen Postfach.

## Kompakte Mailantworten und mobile Ansicht

Neue Tages-/Wochenübersichten zeigen Betreff, Absender und lokal formatierte Zeit.
Technische Ordner-, Zeitzonen- und Vollständigkeitshinweise werden nicht pauschal
an jede Antwort angehängt. Vorhandene Zeitzonen und auswertbare Headerdaten werden
intern aufgelöst. Nicht zeitlich zuordenbare Nachrichten werden nicht als Treffer
im angefragten Zeitraum angezeigt; die Originalbelege bleiben erhalten. Eine leere
Auswahl wird als Ergebnis der abgerufenen Nachrichten formuliert, nicht als Beweis
eines leeren Postfachs.

Neue Aufträge speichern `mail_overview_version=2` im vorhandenen Binding. Alte
Aufträge ohne Versionsfeld werden unverändert mit Version 1 rekonstruiert. Damit
werden alte Antworten nicht umgeschrieben und Folgefragen bleiben an genau die
ursprünglich angezeigte Auswahl gebunden. Der neue Filter beeinflusst ausschließlich
die neue Anzeige; er entfernt keine Nachrichten oder gespeicherten Belege.

Die Abarbeitung ist standardmäßig unter einer kompakten Zeile „Details Abarbeitung“
eingeklappt, auch während eines laufenden Auftrags. Notwendige Freigaben und
Rückfragen erhalten einen direkten Einstieg. Auf kleinen Bildschirmen blenden sich
die oberen Chatleisten beim tatsächlichen Abwärtsscrollen aus; Aufwärtsscrollen,
Tastaturnavigation und ein Wiederherstellungsbutton zeigen sie erneut. Streaming
oder reine Layoutänderungen lösen die Ausblendung nicht aus.

## Projektmodell als gemeinsame Vorgabe

Die Projekteinstellungen speichern `model_policy`: `{}` bedeutet Auto; eine feste
Wahl enthält die ID einer vorhandenen Modellverbindung und deren konfigurierten
Modellnamen. Die Auswahl ändert keine globale Standardverbindung. Verbindungen
müssen aktiv sein und die erforderlichen Text-/Strukturierungsfähigkeiten besitzen.
Nicht mehr verfügbare gespeicherte Modelle werden erkennbar, statt unbemerkt durch
ein anderes Modell ersetzt zu werden.

Projektantworten, projektbezogene Aufgabenanalysen und Aufgabenentwürfe übernehmen
das gewählte lokale Modell. Gespeicherte Aufgaben behalten ihre Spezifikation und
übernehmen die aktuelle Projektwahl beim nächsten Lauf. Projekt-, Anbieter- und
Modellbindung werden vor dem eigentlichen Versand nach einer Wartephase erneut
geprüft. Reine Werkzeugschritte benötigen keinen Modellaufruf. Lokale Hilfsrollen
wie Auftragseinordnung, Titel und Memory-Extraktion behalten ihre eigenen Grenzen.

Eine Cloud-Präferenz kann gespeichert werden; sie ist keine Freigabe bestehender
`LOCAL_ONLY`-Projektinhalte. Solange diese Freigabe fehlt, bleibt die entsprechende
Projektverarbeitung mit verständlichem Grund gesperrt, ohne lokalen Modellfallback.
Persönliches Memory, Quellen, gespeicherte Historie und Integrationsrechte werden
nicht umetikettiert. Dieser Cloud-Pfad ist damit ausdrücklich noch keine nutzbare
Cloud-Projektfreigabe.

Migration 0050 ergänzt nur `projects.model_policy` mit dem Standardwert `{}`.
Vorhandene Projekte behalten dadurch ihr bisheriges Verhalten. Die vorhandene
Projektrevision schützt konkurrierende Änderungen; ein Downgrade mit gespeicherten
Modellpräferenzen wird verweigert.

## Lokale Inferenz und Diagnose

Drei getrennte Grenzen gelten für die lokale Antwortgenerierung:

| Einstellung | Standard | Zweck |
| --- | --- | --- |
| `HUB_LOCAL_QUEUE_TIMEOUT` | 120 s | Freie lokale Modellkapazität abwarten |
| `HUB_LOCAL_FIRST_TOKEN_TIMEOUT` | 120 s | Erstes tatsächliches Antwortfragment abwarten |
| Provider-Timeout / `HUB_LOCAL_TIMEOUT` | 30 s | Stillstand zwischen Antwortfragmenten |

Das vorhandene Gesamtlauflimit bleibt zusätzlich wirksam. Leere Frames und
Heartbeats verlängern die erste Antwortfrist nicht. Eine private Dateisperre im
bereits gemeinsam genutzten Quellenvolume koordiniert lokale Inferenz über
API- und Workerprozesse hinweg. Abbruch gibt den Platz frei; unmittelbar vor
Versand werden vorhandene Berechtigungsprüfungen erneut ausgeführt.
Router, Antwort und Titel prüfen ihre Bindungen nach der Kapazitätswartezeit.
Ein abgebrochener Lauf oder deaktivierter bzw. geänderter Provider darf keinen
nachträglichen Modellversand auslösen. Titel bleiben zusätzlich an die aktuellen
Nachrichtenrevisionen gebunden; gelöschte oder bearbeitete Inhalte werden nicht
nachträglich aus einem alten Titelauftrag übertragen.
Eine Aufgabenanalyse verwendet ihr verbleibendes Aufgabenbudget als Gesamtfrist;
die Inaktivitätsgrenze kürzt es nicht pauschal auf 30 Sekunden. Aufgabenentwürfe
haben eine eigene begrenzte Gesamtfrist. Providerwiderruf und Zeitplanänderungen
werden nach dem Warten unmittelbar vor dem Versand erneut geprüft.

Hintergrund-Embeddingläufe bearbeiten standardmäßig nur einen Eintrag pro Lauf,
mit einem kurzen Zeitbudget. Es entstehen keine neue Queue-Datenbank und kein
zusätzlicher Dienst. Der Modellserver selbst wird dadurch nicht umkonfiguriert.

`GET /api/runtime-status` ist authentifiziert und führt keine Modellinferenz aus.
Es unterscheidet Prozess-/Datenbankzustand, Workerheartbeat, Konfiguration,
vergangene Modell-/Planerproben und beeinträchtigte Einordnung. Ein unbekannter
Zustand wird nicht als einsatzbereit ausgegeben. Der zusätzliche lokale
Provider-Testmodus `planner` prüft zuerst strukturierte Interpretation einer
synthetischen Frage und danach eine echte Werkzeugentscheidung mit der aktuellen
Toolgrammatik. Ziel, Domäne und die passende lesende Zustandsschnittstelle werden
inhaltlich geprüft; kein Werkzeug wird ausgeführt. Er ersetzt keine vollständige
Agentenabnahme. Historische P50-/P95-Werte trennen Kapazitätswartezeit und
Vorbereitung; sie beziehen sich höchstens auf die jüngsten 1.000 lokalen Läufe
der letzten 30 Tage. Der Sperrstatus gilt nur für das gemeinsame App-Volume,
nicht für sämtliche anderen Clients eines Modellservers.

## Gedächtnis und Kontext

Die bestehende Memory-Datenbank bleibt maßgeblich. Unabhängige Pläne und
Entscheidungen teilen nicht mehr versehentlich eine einzige Faktidentität.
Die Annahme eines Kandidaten ersetzt keinen anderen Fakt stillschweigend;
Ersetzung verlangt explizite Ziel-ID und aktuelle Revision. Korrekturen,
Duplikate, Quellenprüfung, Vergessen und Übertragungsrechte bleiben nachvollziehbar.

Lexikalische und semantische Treffer werden zusammengeführt. Ältere relevante
Erinnerungen fallen nicht allein wegen einer vorgeschalteten Liste der jüngsten
Einträge heraus. Semantische Abdeckung und Grenzen bleiben sichtbar.
Quellengebundene Zusammenfassungssegmente erhalten ältere Themen über längere
Gespräche hinweg; aktuelle Quellrevisionen und ein Bytebudget begrenzen den
Kontext. Ein Dokument wird dadurch nicht zu einer vertrauenswürdigen Anweisung.
Versteckte Interpretationsläufe bleiben über eine serverseitige Eigentümerzuordnung
im vorhandenen Snapshot an ihr Gespräch gebunden. Die bestehende Löschvorschau,
Aktivitätsprüfung und endgültige Gesprächs-/Projektlöschung schließen diese
Kontexte ein; sie bilden kein unabhängiges dauerhaftes Privatarchiv.

Aufgabenanalyse und Agentenaufgaben verwenden einen gemeinsamen begrenzten
Kontextassembler für ausdrücklich gebundene Quellen, Projektanweisungen und
relevante Erinnerungen. Quellen, Verbindungsrechte und Revisionen werden vor
Verwendung erneut geprüft. Private Kontexte werden nicht automatisch extern geteilt.

Fehlgeschlagenes Lernen kann ausdrücklich und begrenzt wiederholt werden.
Archivierte Quellen sind als solche erkennbar. Eine ausdrücklich verselbstständigte
Erinnerung beginnt lokal und übernimmt keine frühere Cloudfreigabe.

## Bedienung und Datenmigration

Ein gemeinsamer Navigationsschutz deckt ungespeicherte Editoränderungen,
Browser-Zurück und Bereichswechsel ab. Bestehende Aufgabenentwürfe lassen sich
innerhalb des Browsertabs wieder aufnehmen. Zugangsdaten werden nicht als
Entwurfsdaten gespeichert. Dialoge unterstützen Fokusführung und Escape.
Verwaltungsmodus und Agentenaktualisierungen bleiben dem jeweiligen Gespräch
zugeordnet; verspätete Antworten dürfen keinen anderen Chat überschreiben.

Migration 0048 ergänzt ausschließlich Summarysegmente und Wiederholungszähler.
0049 ergänzt den Probe-Typ an vorhandenen Provider-Testbelegen. Bestehende Daten
bleiben erhalten. Downgrades verweigern das Verwerfen neuer belegter Daten.
Vor einer VM-Migration sind die verschlüsselte Sicherung, exakte Ausgangsversion,
Schema und Konfigurationsoriginale zu prüfen. Ein erfolgreicher Backup-Lauf ist
kein Nachweis einer entschlüsselten Wiederherstellung.

## Qualitätsnachweise

Deterministische Unit-/API-/Browserprüfungen, echte lokale Modellproben und reale
Integrationsabnahmen werden getrennt berichtet. Synthetische Serviceantworten
belegen Vertrags- und Fehlerpfade, nicht die Verfügbarkeit eines echten Kontos.
Die Prompt-Evaluation muss Paraphrasen, Folgefragen, mehrere Ziele, leere/große
Ergebnisse, Fehler und semantische Ergebnisse prüfen. Ein Ziel von 98 Prozent
auf einer definierten Kernmenge ist eine Releaseanforderung, kein bereits
beobachtetes Ergebnis. Konkrete ausgeführte Prüfungen und offene Fälle stehen
in `STATUS.md`; private Betriebsbelege bleiben außerhalb von Git.

## Abdeckung je Adapter

| Adapter | Technisch vorhandene Rolle | Grenze der Abnahme |
| --- | --- | --- |
| Home Assistant | Feste Zustands-/Zugriffsabfragen und allgemeine freigegebene HTTP-/WebSocket-Administration | Allgemeine Konfiguration/Updates brauchen konkrete Ziel- und Wiederherstellungsbelege; reine Erreichbarkeit beweist keine Inventarabfrage. |
| Paperless | Gebundene Dokumentensuche/-inhalte, freigegebene Verwaltungs-API | Dokumentwissen und technischer Dienststatus werden getrennt; große OCR-Inhalte werden begrenzt weitergegeben. |
| Proton über MCP | Freigegebener Katalog, lokale Suche, Inhalte und begrenzte Antwortbeziehungen | Unbekannter Antwortstatus bleibt unbekannt; kein Beweis vollständiger Postfachhistorie. |
| Gmail | Konfigurierbarer lesender Postfachadapter | Antwortbeziehungs-Abgleich und Versand sind keine stillschweigend vorhandenen Fähigkeiten. |
| Google Drive | Optionale Wissensquelle und einzeln freigegebene Dateiablage | Keine allgemeine Agentenadministration oder implizite Schreibfreigabe. |
| SSH | Feste Inspektion und ausdrücklich freigegebene Befehle/Dateizugriffe | Rechte des Remote-Kontos, ausgewähltes Ziel und aktuelle Autonomieregeln bleiben maßgeblich. |
| UniFi | Aktuell freigegebene HTTP-Schnittstellen | Kein universeller, automatisch validierter Controller-Katalog. |

Die Oberfläche unterscheidet zugeordnete Verbindungen von tatsächlich bereitgestellten
Funktionen. Fehlende konkrete Rollen werden als fehlende Fähigkeit behandelt;
aktivierte Verbindungen garantieren keine beliebige Anfrageabdeckung.
