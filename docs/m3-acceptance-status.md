# M3-Abnahme: Umsetzung und offene Grenzen

Die konkreten Belege sind in STATUS.md und der Anforderungsmatrix referenziert.
Diese Liste trennt implementierte Funktionen und noch fehlende Funktionen.

| Funktion | Nachweis / Grenze |
|---|---|
| Tool-Gateway, versionierte Parameter, fünfminütige Freigaben, globale Schreibpause | API-/PG-Tests und live Abnahme vorhandener begrenzter Aktionen |
| Skills: Versionen, Auswahl, Vertrauen, Rechte bleiben unverändert | lokale Tests, CI und live Prüfung |
| Task-Center mit Dialog, Termine, Dokumentauslöser, Ergebnisse und Historie | UI/PG-Abnahme; vorhandener n8n-Minutenworkflow |
| Aufgabenbezogene n8n-Vorlage, Veröffentlichung, Callback, lokale Ausführung | reale Execution 276; Testworkflow deaktiviert, Aufgabe archiviert |
| MCP-Katalog und parameterfreie explizite Text-Lesewerkzeuge | HTTP-/UI-Tests, Schema/Revision/Allowlist; keine echten MCP-Ziele angefordert |
| Passive Browserprüfung mit Bild und Text | echter Chromium-Container, Sandbox und Netzwerksperre geprüft; nur fest freigegebene Ziele |
| HA-Status, Backupmetadaten und Wartungsplan als Hintergrundaufgabe | realer PostgreSQL-Worker mit HA 2026.9.3 / 61 Backupmetadaten, null Writes |
| Systemberichte im Chat / natürliche Aufgabenentwürfe | lokale Grenzen, gespeicherte Belege, echte lokale Router-/HA-Abnahme und installierter Samstag-02:00-Entwurf bestanden |
| Aufgabenprofile und Schreibfreigaben | implementiert für genau eine wiederherstellbare lokale Projektarchivierung: Einzelfreigabe oder revisionsgebundene Autonomie mit Ablaufzeit, Widerruf, Verbrauch und unveränderlicher Historie; keine externen Writes |
| obdaAI-Backup / temporärer Restore | Schema 0022, 23 Dateiversionen, 46 Originalhashes, Memory-Dateien, Schlüssel und Workflowbelege geprüft |

## Noch fehlend

- Interaktiver Browser mit getrennten Sitzungen, menschlicher Anmeldung und
  2FA-Übergabe. Die passive Browserprüfung bietet diese Funktion nicht.
- Allgemeine mehrstufige n8n-Graphgenerierung aus dem Chat. Die vorhandene Vorlage
  nutzt einen geprüften festen Graph; Modellcode oder beliebige Nodes fehlen.
- Weitere explizite MCP-/API-Aktionen und externe Writes mit eigener Abnahme.
- Zusätzliche Task-Schreibadapter, insbesondere externe Wartung. Die drei Profile
  sind für eine konkrete lokale Projektarchivierung implementiert; daraus entstehen
  keine Freigaben für andere Systeme, Schritte oder Folgeaktionen.
- HA-Wartung mit Komponenten-/Versionsgrenzen, verifizierter Archivintegrität,
  Wiederherstellungsschlüssel und nachgewiesenem Restore. Gemeldete Backups
  bestätigen diese Voraussetzungen nicht. Produktiver Restore wurde nicht getestet.
- Vollständige Wiederherstellung der externen n8n-/HA-Systeme sowie gemessene RTO/RPO.

M3 ist deshalb noch nicht vollständig abgenommen. Eine erfolgreiche obdaAI-
Datenbankwiederherstellung ersetzt keine Wiederherstellungsprobe von Home Assistant.

06.10.2026: Natürliche Aufgabenentwürfe können eine geordnete Folge von maximal
fünf festen Lese-/Analyseschritten vorschlagen; ausführbarer Modellcode, freie Nodes,
URLs und Schreibadapter bleiben ausgeschlossen. Der normale Dialog zeigt die
Schrittfolge und bietet „Arbeitsraum prüfen und lokal auswerten“. Frühere lokale
Statusbelege werden jetzt ausdrücklich als LOCAL_ONLY-Daten an die anschließende
Analyse gebunden und in deren Eingabebeleg gespeichert. Kein implizites Aktivieren,
keine HA-Berichte als Modellkontext und keine neuen externen Rechte. Diese lokale
Pipeline nutzt weiterhin denselben Aufgabenmotor bei n8n-Aufrufen; allgemeine
beliebige n8n-Graphgenerierung ist damit noch nicht abgenommen.

Reale Task-Schreibabnahme auf eigener VM/Schema 0021 bestanden: `confirm_each`
wartete vor dem Effekt auf die konkrete Freigabe; `bounded_autonomous` verbrauchte
seinen begrenzten Grant. Jeweils eigenes leeres synthetisches Ziel genau einmal
archiviert, Revision genau +1, zwei Schritte und Aktionsbeleg; Wiederholung derselben
Anfrage lieferte denselben Lauf. Eigene Testaufgaben anschließend archiviert und
globale Schreibpause wieder aktiv. Keine externen Schreibaktionen.


Dokumentauslöser `source_ready` sind mit Schema 0022 auf der eigenen VM installiert.
Echte vorhandene n8n-Uhr, lokale Lesearbeit, Pause/Bestand/revisionsgebundene
Ereignisbelege und ausbleibender Doppelrun nach erneuter Verarbeitung wurden geprüft.
Die zusätzliche lokale Ereignis-Analyse erhält nur eine ausdrücklich ausgewählte
synthetische Quelle und den exakten lokalen Lesebeleg; der neue auslösende Text
ist nicht Teil des Modelleingangs. Keine externen Rechte oder neuen n8n-Workflows.
Details und Grenzen: source-ready-tasks.md. Weitere Ereignistypen bleiben offen.
