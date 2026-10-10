# M1: Provider, Secrets und Grenzen

Einstellungen verwaltet mehrere lokale OpenAI-kompatible Verbindungen und OpenRouter.
Pro Typ ist höchstens ein AUTO-Standard erlaubt. Endpunkte für lokale Verbindungen
müssen vorher in `HUB_LOCAL_ENDPOINTS_JSON` (Base-URL → erlaubte IP) oder im bestehenden
lokalen Serverziel freigegeben sein. DNS, Redirects und öffentliche lokale Ziele werden
geprüft; OpenRouter ist an seine offizielle HTTPS-Adresse gebunden. Fähigkeiten und
Datenschutzklassen sind deklarierte Anforderungen, keine automatisch erteilten Rechte.
Ein Verbindungstest liest den Modellkatalog; der persistente Modelltest nutzt nur
„What is 2 plus 2?“ und läuft über dieselbe Queue wie Chat, auch ohne offenen Browser.

API-Schlüssel werden mit AES-256-GCM, zufälligem Nonce und Provider-ID als AAD
verschlüsselt gespeichert. `HUB_SECRETS_KEY_FILE` zeigt auf eine private Base64-Datei
mit genau 32 zufälligen Bytes. Der Schlüssel bleibt außerhalb der Datenbank und wird
in Compose nur lesbar eingebunden. Die vorhandene verschlüsselte Konfigurationssicherung
enthält `/etc/obdaai`, damit auch der Masterkey wiederherstellbar ist. Verlust dieses
Keys macht DB-Secrets unlesbar; DB und Masterkey getrennt gegen unberechtigten Zugriff
schützen. API, Revisionsliste und Validierungsfehler geben keine Secrets zurück.
Änderungen erzeugen Revisionen; laufende Aufträge nutzen ihren ausgewählten Stand.
Öffentliche Verbindungstests aktualisieren Preis-Metadaten mit eigener Revision.
Die serverseitige Cloud-Sperre bleibt verbindlich. Auf ausdrücklichen Benutzerwunsch
startet gewöhnlicher Chat im sichtbaren Modus „Auto · Lokal + Cloud“; dies bindet die
Cloudfreigabe an die aktuelle Eingabe beziehungsweise Bearbeitungs-/Retryrevision.
Alte LOCAL_ONLY-Historie, Projekte und Wissensquellen werden dabei nicht nachträglich
freigegeben. „Nur lokal“ hat für den gewählten Lauf Vorrang.

Vor jedem Cloudlauf wird unter Provider-Zeilensperre eine Kostenreservierung angelegt.
Dazu müssen aktuelle Katalogpreise (höchstens eine Stunde alt), ein positives Monatsbudget
und ein Limit je Lauf vorliegen. Fehlende/veraltete Preise werden für eine tatsächlich
freigegebene Cloud-Anfrage einmal aus dem öffentlichen Modellkatalog aktualisiert,
ohne Gesprächsinhalte. Schlägt dies fehl, startet kein kostenpflichtiger Modellaufruf.
Private Anfragen lösen keine externe Preisprüfung aus. UTF-8-Inhaltslänge plus Nachrichtenoverhead und maximale
Ausgabetokens ergeben eine konservative Schätzung. Das ist kein exakter Tokenizer und
keine Garantie gegen andere Abrechnungskomponenten oder Preistierwechsel des Anbieters.
Für eine harte Geldgrenze ist zusätzlich ein entsprechendes Provider-Kontolimit nötig.
Fehlende Usage ist **unbekannt**, die Reservierung bleibt bestehen; nur gemeldete Usage
ersetzt die Schätzung. Gesprächslöschung löscht keine Kostenreservierungen.

OpenRouter meldet Usage einschließlich Kosten im letzten SSE-Chunk; zusätzliche
`stream_options.include_usage` ist in der aktuellen API veraltet.
[Offizielle Usage-Dokumentation](https://openrouter.ai/docs/cookbook/administration/usage-accounting).
Preise und Kontextgröße kommen aus dem
[offiziellen Modellkatalog](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties).

Grenzen: konfigurierte Kontextzeichen/Tokens, begrenzte Ausgabe und höchstens eine
Router-Schemareparatur. `HUB_RUN_TIMEOUT` begrenzt Einordnung und Vorbereitung
(standardmäßig 90 Sekunden). Die anschließende Antwortgenerierung erhält ein eigenes
Gesamtzeitbudget über `HUB_GENERATION_TIMEOUT` (standardmäßig 600 Sekunden,
zulässig 30–900 Sekunden). Bereits laufende Antwortausgabe wird damit nicht durch
die ursprüngliche Vorbereitungsfrist abgebrochen. Die vorhandenen HTTP-Zeitlimits
begrenzen zusätzlich ausbleibende Providerdaten; regelmäßige Streamteile allein
heben das Gesamtzeitbudget nicht auf.

Zeitüberschreitung, unterbrochene Ausgabe, Token-/Ausgabegrenze oder Content-Filter
bleiben fehlgeschlagene Läufe. Bereits empfangene Antwortteile, erfasstes Modell,
Quellen und Laufhistorie werden erhalten. Die Antwort trägt den sichtbaren Hinweis
„Teilantwort · unvollständig“ beziehungsweise bei Benutzerabbruch „Teilantwort ·
abgebrochen“. Spezifische Fehlermeldungen unterscheiden die Zeitgrenze, ausbleibende
Providerdaten und überschrittene Ausgabegrenzen; Wiederholen erzeugt einen neuen
Lauf. Ein Stream ohne ordentlichen Abschluss wird nicht als fertige Antwort gewertet.
`/api/metrics` ist authentifiziert und zeigt aggregierte Laufzustände, Routerzeit, erste
Antwort, Dauer und bekannte Kosten der letzten 30 Tage ohne Texte oder Secrets.
Loginversuche sind datenbankgestützt begrenzt und gelten gemeinsam für beide API-Prozesse.

Das synthetische Router-Dataset `tests/fixtures/router-cases.json` deckt einfache deutsche
und englische Fragen, kombinierte Fähigkeiten, Werkzeuge, Wissen, Artefakte, Termine und
Prompt-Injection und Anschlussfragen ab. Einfache Fragen müssen genau einen Router-HTTP-Aufruf nutzen. `scripts/evaluate_router.py` prüft ausschließlich den lokalen Router;
Modell-/Antwortkosten und externe Werkzeuge werden damit nicht ausgelöst.

Die optionale Ausgangsfreigabe `deploy/egress.sh` gilt nur auf der eigenen obdaAI-VM.
Ohne Operator-Marker ist die App-UID lokal begrenzt. Mit Marker erlaubt sie DNS zum
bestehenden Stubresolver und HTTPS zu den aktuell aufgelösten öffentlichen IPv4-Adressen
von OpenRouter. Die CDN-Adressen können geteilt sein; Host-, TLS- und Payloadprüfung
im Adapter bilden die zusätzliche Grenze. Bei Adresswechsel Filter gezielt neu laden;
IPv6 bleibt gesperrt. Kein allgemeiner Internetzugang und kein Cloud-Fallback.

Die Routerantwort ist vollständiges JSON ohne Zwischenstücke. Ihr HTTP-Leselimit
folgt deshalb dem Vorbereitungsbudget (`HUB_RUN_TIMEOUT`), während Verbindung,
Schreiben, Pool-Warten und der Antwortstream das Provider-Inaktivitätslimit behalten.
Eine gültige lokale Routerantwort benötigte in der VM-Diagnose rund 30 Sekunden;
die bisherige 30-Sekunden-Lesegrenze konnte bereits davor abbrechen.


## Routing in den Einstellungen

Einstellungen → Routing macht die Modellauswahl beeinflussbar. „Ausgewogen“ nutzt
für einfache Wünsche die lokale Einordnung und bevorzugt ausdrücklich komplexe
Recherche/Analyse in der Cloud, sofern die entsprechende Option aktiv ist.
„Lokal bevorzugen“ übernimmt die Modellklasse aus der lokalen Einordnung ohne
zusätzlichen Komplexitätsaufschlag; diese Strategie garantiert keine ausschließlich
lokale Verarbeitung. Dafür gibt es „Nur lokal“. „Cloud bevorzugen“ bevorzugt
Cloudmodelle für generierte Antworten. Lokale Systemauskünfte bleiben lokal.

Die Komplexitätsregel prüft klar benannte komplexe/umfassende/detaillierte Recherche-,
Analyse-, Vergleichs-, Bewertungs- oder Strategiewünsche. Sie ist eine transparente
Regel, keine objektive Qualitätsmessung und kein Beleg für die Fähigkeiten eines
bestimmten Modells. Das aktuelle Fachthema allein erzwingt keinen Cloudaufruf.

Die serverseitige revisionierte Speicherung lehnt veraltete Änderungen mit 409 ab.
Neue Läufe erhalten einen eingefrorenen Regelstand; spätere Einstellungsänderungen
ändern laufende Antworten nicht. `GET/PUT /api/routing-settings` liest/speichert die
Regeln. `POST /api/routing-settings/preview` wendet die gespeicherten Regeln ohne
Provideraufruf auf einen Testprompt an. Die Vorschau erklärt Präferenz und Grenzen;
die echte lokale Einordnung kann später abweichen.

Die Laufhistorie zeigt die tatsächliche lokale Einordnung, Regelentscheidung,
verbleibende Datenschutz-/Serversperren und den erfassten Antwortanbieter samt
Modell. Eine bevorzugte Cloudroute bleibt lokal, wenn „Nur lokal“, Serverabschaltung,
fehlende Gesprächsfreigabe oder LOCAL_ONLY-Kontext sie sperren. Öffentliche,
laufgebundene Webtreffer können bei erlaubtem Auto in die Cloudantwort einfließen;
private Historie/Projektquellen werden niemals automatisch dafür freigegeben.
Der Einstellungsbereich zeigt außerdem die konfigurierten Cloudmodelle,
Antworttokenlimits und Kostenbudgets und verlinkt direkt zu „Modelle“. Routing
ändert diese Grenzen nicht; ein kurzes Tokenlimit kann eine lange Recherche
weiterhin abbrechen. Kosten-, Provider- und finale Ausgangsprüfungen bleiben
erhalten. Ein lokaler
Providerfehler löst keinen stillen Wechsel in die Cloud aus.

Implementiert; die releasegebundene CI- und echte VM-Abnahme wird in STATUS erfasst.
