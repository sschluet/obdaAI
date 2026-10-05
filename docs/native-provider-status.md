# Direkte Textanbieter: Protokollgrenze für M5

Die native Transportgrenze für OpenAI Responses und Anthropic Messages ist vorhanden
und mit synthetischen HTTP-Antworten geprüft. Sie ist noch nicht vom produktiven
Chatrouter oder Einstellungsdialog auswählbar. Kein echter Zugang eingerichtet,
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

Nächster Integrationsschritt: unveränderlich an den gewählten Anbieter gebundene
Gesprächsfreigaben, eigene Serverallowlist, verschlüsselte Konfiguration, Budget-
reservierung und deutlich als Schätzung ausgewiesene Laufkosten. Erst danach
Auswahl im Dialog und Abnahme des vollständigen Ablaufs. M5 bleibt offen.
