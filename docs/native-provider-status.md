# Direkte Textanbieter: Protokollgrenze für M5

Die native Transportgrenze für OpenAI Responses und Anthropic Messages ist vorhanden
und mit synthetischen HTTP-Antworten geprüft. Im Entwicklungsstand ist sie mit
verschlüsselter Konfiguration, Budgetreservierung und normalen Einstellungsdialogen
integriert und auf der eigenen VM mit Schema 0021 installiert. Kein echter nativer Zugang eingerichtet,
kein bezahlter nativer API-Test, keine neue produktive Ausgangsfreigabe.

Die Grenze prüft LOCAL_ONLY und genaue Quelle/Revision/Anbieter-Freigabe **vor DNS**.
OpenRouter-Freigaben autorisieren keinen direkten Anbieter. Feste offizielle HTTPS-
Ziele, öffentliche geprüfte IPs, SNI, kein Proxy, Redirect, Tool, Promptcache-Auftrag
oder automatischer Wiederholungsversuch. Textrollen und Kontext/Ausgabe/SSE-Frames
sind begrenzt; unvollständige oder fehlerhafte Streams werden nicht als fertig gemeldet.
OpenAI erhält `store:false`, `background:false`, normales Service-Tier und keine
hosted tools. Dies ist keine Zusage einer Zero-Data-Retention beim Anbieter.

Native Usage liefert eine **Kostenschätzung**, keine Rechnung. Standardpreise vom
05.10.2026: GPT-4.1 mini $0.40/$1.60 pro Million Input/Output; Claude Haiku 4.5
$1/$5. Unbekannte Modelle oder mehr als sieben Tage alte Preisprüfungen blockieren
vor Netzwerkzugriff. Fehlende Usage bleibt unbekannt; unerwartete Cache-Erstellung
wird abgewiesen. Cache-Reads werden vorsichtig mit vollem Inputpreis geschätzt.

Quellen: [OpenAI Streaming](https://developers.openai.com/api/docs/guides/streaming-responses),
[OpenAI Modellpreise](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
[Anthropic Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming),
[Anthropic Modellpreise](https://platform.claude.com/docs/en/models/haiku-4-5/overview).

Schema 0021 bindet ein Gespräch unveränderlich an den beim Anlegen gewählten Anbieter.
Bestehende Gespräche bleiben auf OpenRouter gebunden. Nachrichtenedits benötigen
weiterhin eine eigene Inhaltsrevision-Freigabe. Lokale Projekt-/Vault-Kontexte bleiben
lokal; eine bloße Auswahl gewährt keine Übertragung. Synthetischer API-Gesamtablauf
prüft private lokale Antwort, freigegebenen direkten Stream, konkrete Reservierung,
verschlüsselten Schlüssel und als Schätzung gekennzeichnete Kosten.

`HUB_EXTERNAL_PROVIDER_KINDS` ist eine serverseitige JSON-Liste; Standard bleibt nur
OpenRouter. Nur ausdrücklich eingerichtete eigene Anbieter ergänzen. Es werden keine
Firewalls, Keys oder Freigaben automatisch aktiviert. Normale Modell-Dialoge erlauben
Vorbereitung, zeigen feste Adressen, Modellvorschläge und gesperrte Tests für einen
nicht freigegebenen Anbieter. Neues Gespräch: separater Anbieter und explizite
Gesprächsfreigabe. Wechsel benötigt ein neues Gespräch. Native Adapter derzeit nur
Text; Tool-/Bild-/Embedding-Ausführung ist nicht Teil dieser Anbindung.

`Run.cost_basis` unterscheidet `usage_estimate`, `provider_reported` und `unknown`.
Die Laufhistorie und Metriken unterscheiden Schätzung und Provider-Meldung; fehlende
Usage behält die volle Reservierung. Ein Kontext- oder Streamfehler wird nicht erneut
kostenpflichtig ausgeführt. Die produktive Native-Live-Abnahme benötigt dedizierte
Zugänge und Zielfreigaben und bleibt offen. M5 bleibt teilweise umgesetzt.

Schema 0021 ist mit `ee7ab0f` auf der eigenen VM installiert. Beide APIs gesund;
zehn echte PostgreSQL-Integrationsfälle separat bestanden. Keine neuen nativen
Schlüssel oder Ausgangsfreigaben aktiviert. Eigener Restore prüft Schema 0021
und vorhandene Schlüssel; fehlende native Live-Tests bleiben offen.
