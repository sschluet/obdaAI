# MCP-Verbindungen

Unter Einstellungen → Verbindungen → MCP-Verbindung hinzufügen werden Name,
Serveradresse, Protokollversion und optional ein Bearer-Token als Entwurf gespeichert.
Speichern kontaktiert kein Ziel. Bearer-Tokens sind mit dem vorhandenen Masterkey
verschlüsselt; API und Revisionshistorie geben sie nicht zurück. Bei Änderung des
Ziels oder der Anmeldeart wird der alte Token entfernt, sofern kein neuer angegeben
wurde. Archivieren ist umkehrbar.

Die Prüfung liest ausschließlich den Werkzeugkatalog. Kein `tools/call`, kein
Sampling, keine Freigabe und keine automatische Übernahme in Modellkontext. Fremde
Namen, Beschreibungen und Schemas sind untrusted data und werden nicht ausgeführt.
Ein Ergebnis gilt nur für die geprüfte Einstellungsrevision; ein zwischenzeitlich
geänderter Eintrag verwirft das Ergebnis. Jede Änderung hat eine neue Revision.

Streamable HTTP mit JSON oder Request-SSE ist unterstützt. Protokoll 2026-07-28
verwendet die stateless Request-Metadaten und Method-/Version-Header; 2025-11-25
und 2025-06-18 verwenden Initialize und eine begrenzte Session-ID. OAuth, stdio,
altes HTTP+SSE, interaktive Ergebnisse und entfernte Schreibaktionen sind noch offen.

Der Operator muss vor echten Prüfungen `HUB_MCP_ENDPOINTS_JSON` als exakte
URL→IP-Zuordnung einrichten und das konkrete Netzwerkziel separat freigeben.
Standard `{}` erlaubt keine Prüfung. Kein automatisches DNS, Redirect oder Proxy;
fester Host/TLS-SNI und Zertifikatsprüfung. Öffentliches HTTPS ist möglich, privates
Netzwerk verlangt einen gesonderten geprüften Adapter. HTTP nur für isolierte
Loopback-Fixtures. Kein Nutzer hat aktuell einen realen MCP-Server angefordert.

Begrenzt auf 20 Sekunden Gesamtbudget, höchstens acht Sekunden je Anfrage, 1 MB
je Antwort, acht Katalogseiten und 128 Werkzeuge. Komprimierte Antworten werden
abgewiesen. Kein Schema-$ref-Abruf. Serverfehler werden ohne Rohantwort/Secrets
gespeichert. Katalogprüfungen enthalten einen Inhaltsdigest.

Schema 0016 ergänzt Connection-, Revisions- und Prüfbelegtabellen; ein Downgrade
verweigert sich bei vorhandenen Daten. Die bestehende obdaAI-Sicherung erfasst
diese Tabellen über den vollständigen PostgreSQL-Dump. Bestehende HA-/Scheduler-
Compose-Overlays müssen bei einem Rollout weiterhin eingebunden bleiben.

Abnahme: lokale API-/Transporttests, synthetischer echter HTTP-Dialog mit Reload,
Archivieren/Wiederherstellen, mobile CI sowie PostgreSQL-Parallelrevision und
Prüfdrift. Dies belegt den Adapter, noch keine reale Drittanbieteranbindung.

Spezifikation: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http

## Begrenzte Lesewerkzeuge

`HUB_MCP_READ_TOOLS_JSON` bindet URL, Werkzeugname und SHA-256 des kanonischen
Eingabeschemas. Nur Schemas für ein leeres Objekt mit `additionalProperties:false`
werden unterstützt. Keine Eingabeparameter und kein Modellcode. Ein aktueller
Katalogcheck und unveränderte Verbindungsrevision sind zusätzlich erforderlich.
Vor jedem Aufruf wird der Katalog erneut gelesen und der Digest geprüft.
Anmerkungen wie `readOnlyHint` erteilen keine Rechte.

Unter Verbindungen erscheint für freigegebene Werkzeuge ein eigener Lesebutton.
Der Action-Gateway speichert einen dauerhaften Ergebnisbeleg; dieselbe Aktions-ID
liefert diesen ohne erneuten RPC. Archivierung und Revision sind am letzten
Ausführungsrand gesperrt geprüft. Ergebnisse sind untrusted LOCAL_ONLY und
werden niemals automatisch in Modellkontext übernommen. Maximal 16 Textblöcke
mit insgesamt 64.000 Zeichen; Bilder, Ressourcen und interaktive Antworten werden
abgewiesen. Keine echten MCP-Ziele freigegeben: Produktion bleibt `{}`.
