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
Die serverseitige Cloud-Sperre gilt zusätzlich zur ausdrücklichen Gesprächsfreigabe.
Nachrichtenedit widerruft die alte Inhaltsfreigabe und braucht eine neue Opt-in-Auswahl.

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

Grenzen: konfigurierte Kontextzeichen/Tokens, HTTP-Timeout, maximal 90 Sekunden pro
Gesamtlauf, begrenzte Ausgabe und höchstens eine Router-Schemareparatur. Tokenlimit oder
Content-Filter werden als Fehler sichtbar, Teilantwort und Laufhistorie bleiben erhalten.
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
