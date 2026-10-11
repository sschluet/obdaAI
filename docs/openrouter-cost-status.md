# OpenRouter: Guthaben und Nutzungskosten

Unter **Einstellungen → Modelle** zeigt jede OpenRouter-Verbindung einen eigenen
Guthaben- und Kostenstatus. Im Chat ist dieselbe Übersicht über **Cloudkosten**
erreichbar. Die Anzeige ist eine Statusabfrage; sie erzeugt keine Modellantwort.

## Drei unterschiedliche Beträge

| Anzeige | Bedeutung |
| --- | --- |
| OpenRouter-Kontoguthaben | Aufgeladenes Kontoguthaben abzüglich der kontoweiten Nutzung. Es umfasst auch andere Anwendungen und API-Schlüssel dieses OpenRouter-Kontos. |
| API-Schlüsselnutzung und Restlimit | Nutzung des für diese Modellverbindung gespeicherten Inferenzschlüssels. Ein optionales Restlimit dieses Schlüssels ist kein Kontoguthaben. Ohne gesetztes Schlüssellimit wird kein erfundener Restbetrag angezeigt. |
| Lokales Monatsbudget | In obdaAI für diese Verbindung erfasste, gemessene oder geschätzte Kosten und offene Reservierungen im UTC-Kalendermonat. Andere Anwendungen sind hier nicht enthalten. |

Alle Beträge sind in USD. Anbieterwerte können zeitversetzt eintreffen. Der
Zeitpunkt der letzten Abfrage und ein Hinweis auf veraltete Daten bleiben sichtbar.
Eine nicht verfügbare Abfrage bedeutet **unbekannt**, nicht 0 USD.

Das lokale Monatsbudget bleibt die vorhandene Ausführungsgrenze. Ein hohes
OpenRouter-Guthaben hebt weder dieses Budget noch Datenschutz- oder
Serverfreigaben auf. Offene Reservierungen ohne abschließende Nutzungsdaten
belegen weiterhin Budget; die Übersicht weist sie getrennt aus.

## Kontoguthaben einrichten

1. Die vorhandene OpenRouter-Modellverbindung mit ihrem normalen API-Schlüssel
   weiterverwenden. Dieser Schlüssel liefert seine eigene Nutzung und sein Limit.
2. Für das gesamte Kontoguthaben optional einen **separaten Kontostatus-Schlüssel
   mit Management-Berechtigung** bei OpenRouter erstellen.
3. Diesen ausschließlich im entsprechenden Kontostatus-Feld der Einstellungen
   speichern. Er wird separat verschlüsselt, nicht im Browser zurückgegeben und
   nicht für Modellaufrufe verwendet.
4. **Status aktualisieren** wählen. Ohne gültigen Kontostatus-Schlüssel bleibt das
   Kontoguthaben unbekannt; die normale Schlüsselnutzung kann trotzdem erscheinen.

Der Kontostatus-Schlüssel lässt sich wieder entfernen. Der Inferenzschlüssel
bleibt davon unabhängig. OpenRouter Management Keys besitzen weitergehende
Berechtigungen als normale Inferenzschlüssel; obdaAI verwendet den separaten
Schlüssel ausschließlich zur lesenden Guthabenabfrage und sendet ihn nur an den
festen offiziellen OpenRouter-Endpunkt.

## Aktualisierung und Fehler

Das Öffnen der Übersicht liest zunächst nur den lokalen Cache. **Status
aktualisieren** fragt die Metadaten ab; Wiederholungen innerhalb von 60 Sekunden
nutzen denselben Cache. Ein Serverneustart leert den Cache. Änderungen der
Verbindung oder des Schlüssels machen alte Werte ungültig.

Bei fehlendem Schlüssel, deaktivierter Cloud, verweigerter Berechtigung oder
Netzwerkfehler bleibt eine konkrete Statusmeldung sichtbar. Die Abfrage überträgt
keine Chattexte, Wissensquellen oder persönlichen Profilangaben. Sie lädt kein
Guthaben nach und verändert keine Limits.

## Quellen und Abnahme

OpenRouter dokumentiert [Schlüsselmetadaten unter `/api/v1/key`](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key)
und [kontoweite Summen unter `/api/v1/credits`](https://openrouter.ai/docs/api/api-reference/credits/get-credits).
Die Kontoguthabenabfrage benötigt Management-Berechtigung.
[Management Keys](https://openrouter.ai/docs/guides/overview/auth/management-api-keys)
sind getrennte Administrationsschlüssel und können keine Modellantworten erzeugen.

Die öffentliche Projektvorstellung verwendet ausschließlich synthetische
Guthaben- und Kostenwerte. Ein Screenshot ist kein Nachweis einer echten
OpenRouter-Kontoabfrage. Echte Abnahme, installierter Stand und noch offene Fälle
werden gesondert in `STATUS.md` geführt.

## Gezielte Serverabnahme

App-Code `3d003f6`, Schema0037 am11.10.2026 auf Testinstanz installiert. Reale
Schlüsselnutzung über bestehenden Inferenzschlüssel abgerufen; Einstellungen,
Chatcache und mobile320/390/768px geprüft. Providerkonfiguration/Budgetgrenzen
unverändert, keine Modellabfrage. Kontoguthaben blieb ohne separat konfigurierten
Management Key unbekannt; dessen echte Einrichtung liegt beim Benutzer.
