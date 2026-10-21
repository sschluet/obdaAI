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

Private Archivfragen verwenden `paperless.read` mit begrenzter Suche und konkretem
Dokumentabruf. Inhaltsfragen benötigen tatsächliche OCR-Belege; eine Trefferliste
genügt dafür nicht. Folgefragen beziehen sich auf weiterhin berechtigte Abrufe
desselben Gesprächs. Dokumentkennungen und Quellenbezüge bleiben vollständig;
gekürzte Ansichten und fehlende Belege werden ausdrücklich ausgewiesen. Eine bekannte
Dokument-ID oder eindeutige Position im letzten gebundenen Suchergebnis ergibt eine
konkrete typisierte Leseentscheidung mit unveränderten Quellenhashes und Konto.
Die tatsächliche Reihenfolge der vollständigen Treffer zählt; freie Assistentenprosa
oder eine gekürzte Vorschau legt keine Kennung fest. Bei verfügbarem gültigem Kandidaten
verhindern native Grammatik und Ausführungsprüfung einen vorzeitigen STOP, eine Rückfrage
oder einen Abschluss vor dem Dokumentabruf. Der bestehende Dispatch prüft aktuelle
Rechte und den konkreten GET-Pfad erneut. Unbekannte oder kontenübergreifend mehrdeutige
Auswahl bleibt im normalen Planungsweg; ungewisse/fehlgeschlagene Versuche werden nicht
automatisch wiederholt. Es entstehen keine Schreib-, Download- oder Cloudrechte.

Release d5940db ist mit echter Dokumentensuche und anschließendem OCR-Abruf des
ersten beobachteten Dokuments samt belegter Zusammenfassung auf der Test-VM
abgenommen. Keine Rückfrage, öffentliche Recherche, Cloud, Schreib- oder Download-
operation war nötig. Der Modellkontext bleibt innerhalb von 14.000 UTF-8-Bytes;
Anbietergrenzen und vorhandene GET-Freigaben bleiben erhalten. Ein zusätzlicher Prüflauf mit dem früheren Archivauftrag ist ebenfalls erfolgreich; sein Wortlaut und seine Ergebnisse bleiben auf der VM.

Auch dbab2a7 ist mit tatsächlicher Suche und Dokument-/OCR-Folgefrage erfolgreich
abgenommen. Diese getrennte Archivabnahme war trotz der damaligen Mailstörung erfolgreich.

Bereits der frühere Stand 43f6af3 ist mit tatsächlicher Suche, anschließendem
Dokument-/OCR-Abruf samt belegter Zusammenfassung sowie dem früheren individuellen
Archivauftrag erfolgreich abgenommen. Das bleibt ein getrennter historischer Beleg.

Diese Abnahme belegt die geprüften Leseabläufe, keine vollständige Archivauswertung
oder allgemeine Administration. Konkrete Änderungen wie Umbenennen bleiben an den
separaten bestehenden Verwaltungsweg mit aktuellen Rechten gebunden.

Jede erfolgreiche Antwort in diesem Leseweg erhält den getrennten Bereich
„Quellen und Suchumfang (Paperless)“ aus aktuellen erfolgreichen typisierten Abrufen: tatsächliche Quelle,
Suchfilter und Seitenangaben, Gesamttreffer genau dieser Suchantwort, zurückgegebene
Dokument-IDs und belegte OCR-Kürzung. Verschiedene Suchen werden nicht addiert;
Ausgabegrenzen, ausgelassene Titel und Belege werden ausdrücklich genannt.
Die Modellantwort wird nicht umgeschrieben und durch den Quellenblock nicht pauschal
als richtig erklärt. Fehlgeschlagene oder nicht mehr gültige relevante Belege
verhindern die Ausgabe als frische Quellenangabe. Das ist lokale Schlussformatierung
ohne weitere Modell-, Werkzeug- oder Netzwerkaufrufe. Eine leere
Suche gilt ausschließlich für den angefragten Suchumfang.
