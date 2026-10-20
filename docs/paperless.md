# Paperless als private Integration

Unter Einstellungen → Integrationen eine Paperless-Verbindung mit der eigenen
Serveradresse und einem Paperless-API-Token speichern und aktivieren. „Zugang
prüfen“ führt einen tatsächlichen lesenden Zugriff aus. Danach öffnet „Dokumente
öffnen“ die serverseitige Suche mit Seitennavigation, Metadaten, OCR-Vorschau und
Originaldownload. Die Oberfläche unterscheidet ausgeschaltet, prüfbar, verbunden,
fehlende Zugangsdaten und noch fehlende Adapter.

## Verwendung in der KI

Die Integrationsauswahl eines Chats oder Projekts bestimmt, welche Archive der
aktuelle Auftrag verwenden darf. Aufgaben übernehmen ohne eigene Auswahl die
Projektbindung; eine ausdrückliche Auswahl oder „aus“ überschreibt sie. Auch
projektbezogene KI Use Cases verwenden die Projektbindung. Nur tatsächlich
gewählte und aktivierte Paperless-Profile werden gelesen.

Die aktuelle Frage beziehungsweise der Use-Case-Prompt samt aktuellen Parametern
liefert begrenzte Suchbegriffe. „Paperless #7“ oder „Dokument 7“ wählt eine konkrete
Dokumentnummer. Es werden höchstens drei Treffer je Profil und insgesamt 12.000
Zeichen als privater Kontext eingelesen. Gekürzte Auszüge sind gekennzeichnet;
ein erfolgloser Suchlauf ist ebenfalls lokal gebunden. Profilrevisionen und
Auswahl werden eingefroren und am Modellübergang erneut geprüft. Deaktivierung
oder Änderung stoppt die Verarbeitung. Archivtexte gelangen nicht zu Cloudmodellen.

„In Projekt übernehmen“ speichert eine private OCR-Kopie als normale Projektquelle.
Wiederholte Übernahme unveränderter Daten erzeugt keine zweite Quelle. Originale
in Paperless bleiben unverändert; die Originaldatei kann separat heruntergeladen
werden. Eine unvollständige große OCR-Vorschau wird nicht als vollständige Quelle
importiert. Schreiben, Hochladen, Metadatenänderung und Löschung in Paperless sind
in dieser lesenden Anbindung nicht umgesetzt.

## Netzwerk und Protokoll

Der Betreiber aktiviert `HUB_INTEGRATION_TARGETS_ENABLED=true` zusammen mit dem
Integration-Egress-Beobachter auf seiner eigenen VM. Aktivierte Profile erhalten
automatisch ihre geprüften numerischen Zieladressen und TCP-Ports; neue Adressen
benötigen keine zusätzliche manuelle Server-Allowlist. Deaktivierte Verbindungen
verlieren diese Freigabe. Eingehende Zugriffe, Proxy-/Modell-/bestehende Quellregeln
und isolierte Parser-/Browser-/Artefaktnetze bleiben getrennt geschützt.

HTTP ist nur für private LAN-Ziele vorgesehen; öffentlich erreichbare Ziele
benötigen HTTPS. TLS-Prüfung, Host und SNI bleiben am numerisch gepinnten Ziel
erhalten. Weiterleitungen, fremde Paginierungsadressen und lokale System-/Cloud-
Metadatenziele werden nicht verwendet. Zugangsdaten bleiben verschlüsselt.

Paperless verwendet `Authorization: Token …` und feste REST-Pfade. JSON-Antworten
sind auf 2 MiB, Originaldownloads auf 20 MiB und OCR-Vorschauen auf 100.000 Zeichen
begrenzt. Die App verarbeitet keine vom Archiv gelieferten Programme oder Makros.
Protokollbezug: [offizielle REST-API](https://docs.paperless-ngx.com/api/) und
[offizielle API-Dokumentation im Repository](https://github.com/paperless-ngx/paperless-ngx/blob/dev/docs/api.md).

Gezielte lokale und synthetische Prüfungen belegen den Funktionsvertrag; tatsächliche
Server-/Schlüsselabnahme ist getrennt in [STATUS](../STATUS.md) dokumentiert.

## Dokumentfragen im gemeinsamen Agentenweg

Private Archivfragen verwenden im neuen Entwicklungsstand `paperless.read` mit
begrenzter Suche und konkretem Dokumentabruf. Inhaltsfragen benötigen OCR-Belege;
eine Trefferliste genügt dafür nicht. Folgefragen beziehen sich auf weiterhin
berechtigte Abrufe desselben Gesprächs. Der Modellkontext bleibt begrenzt, Kürzungen
und fehlende Belege werden ausgewiesen. Bestehende GET-Freigaben werden am Versand
geprüft; dieser Leseweg eröffnet keine Schreib- oder Downloadrechte und nutzt weder
öffentliche Recherche noch Cloud. Echte Abnahme dieses neuen Wegs steht noch aus.
