# Integrationen und kontrollierte Aktionen

**Einstellungen → Integrationen** ersetzt den eigenen Hauptmenüpunkt Werkzeuge
und den bisherigen Einstellungsbereich Verbindungen. Bestehende Werkzeug-Links
öffnen denselben neuen Bereich; der ausgewählte Einstellungsbereich bleibt nach
Neuladen erhalten.

Die Oberfläche gruppiert Funktionen nach Anwendung: Arbeitsraumüberblick,
Home-Assistant-Status/Wartung/Sicherungen, freigegebene Webseiten und Projektarchive.
Lesende Prüfungen starten nur nach Klick. Fortschritt, Ergebnis und gegebenenfalls
Fehler/Wiederholung stehen direkt an der gewählten Karte. Nicht eingerichtete
Verbindungen erklären ihre Einschränkung; Konfiguration gilt nicht als frischer
Verbindungsnachweis. Weitere Dienste und technische Belege bleiben eingeklappt.

Eine Projektarchivierung braucht weiterhin konkrete Freigaben: Ziel über Suche
wählen, Änderungen gegebenenfalls ausdrücklich erlauben, Vorschlag vorbereiten,
genaue Archivierung zeitlich begrenzt freigeben, dann ausführen. Änderungen am Ziel,
Ablauf der Freigabe oder eine Schreibpause verhindern die Ausführung. Abbrechen
widerruft den Vorschlag; Aufklappen oder Lesen aktiviert keine Schreibrechte.
Archivierung bleibt wiederherstellbar und ist getrennt vom endgültigen Löschen.

Modelle, Webrecherche und Aufgaben sind über direkte Verweise erreichbar. MCP-
Verbindungen liegen unter Weitere Dienste verbinden; eine passive Webseitenprüfung
benötigt weiterhin eine am Server freigegebene feste Zieladresse. n8n erhält keine
Aufgabeninhalte oder Dokumente. Das Verschieben ändert keine Backend-Verträge,
Berechtigungen, Zugangsdaten oder Netzwerkregeln; Schema0033 bleibt erhalten.

Die vollständige Archivierung wird mit eigenen synthetischen Projekten geprüft.
Reale VM-Abnahme lässt die globale Schreibpause unverändert und prüft den lesenden
Arbeitsraumaufruf sowie Bedienung und Navigation. Belege stehen in STATUS.md.


## Automatische Nutzung im Chat

Neue Gespräche, Projekte und Aufgaben stellen standardmäßig alle aktivierten
Integrationen bereit. Im Chat zeigt die Auswahl **Automatisch · N verfügbar**.
Die Liste wächst mit später aktivierten Verbindungen; eine gespeicherte manuelle
Auswahl oder **Keine** bleibt wirksam. Projektgespräche übernehmen die Auswahl
ihres Projekts. **Gezielt auswählen** bietet die bisherige begrenzte Einzelauswahl.
Das Öffnen der Liste und die automatische Verfügbarkeit kontaktieren keinen Dienst.

Beim Senden prüft die Oberfläche die Anfrage lokal über den authentifizierten
Routing-Endpunkt. Bekannte System-/Postfachbegriffe und die Verbindungsnamen
bestimmen die passenden vorhandenen Profile. Diese Zuordnung verwendet kein
Cloudmodell, keine Websuche und keine externen Dienstaufrufe. Sie ersetzt keine
allgemeine semantische Erkennung beliebiger Formulierungen. Normale Erklärfragen
bleiben im bisherigen Chat; eine Mailfrage wie **Welche neuen Mails gab es heute?**
startet den gemeinsamen lokalen Werkzeuglauf ohne zusätzlichen Schalter.

Nur die konkret passenden Profile werden an den Auftrag gebunden. Bestehende
Profilrechte, aktuelle Richtlinien, Ziel-/Kontogrenzen, Einzelfreigaben und
Schreibpausen werden weiterhin geprüft. Die automatische Auswahl erteilt keine
neuen Rechte. Ein nur lesendes Mailprofil soll keine HA-/SSH-Änderung in einem
anderen Auftrag blockieren. Eine Anfrage im ausdrücklich gewählten Modus
**Cloud** wechselt für private Systemdaten nicht stillschweigend zu einem lokalen
Modell; die Oberfläche erklärt die nötige lokale Verarbeitung.

Die bloße automatische Verfügbarkeit eines Paperless-Archivs liest keine
Dokumente für gewöhnliche Fragen. Bewusste manuelle Archivbindungen behalten
ihre bisherige lokale Kontextfunktion. Ergebnisse aus Systemen und Postfächern
bleiben lokal und sind untrusted Daten. Die Anwendung friert den Zeitkontext
für jeden Agentenauftrag ein; `HUB_AGENT_TIMEZONE` bestimmt die IANA-Zeitzone
(Standard `Europe/Berlin`). Tagesgrenzen berücksichtigen Sommerzeitwechsel.

Reine Leseaufträge an freigegebene Postfächer beginnen mit ihren tatsächlichen
Werkzeugen statt mit öffentlicher Recherche. Bei MCP wird der Katalog einmal über
den dauerhaften Leseweg geladen; nur beobachtete, unverändert freigegebene
Werkzeugschemas werden als eigener Vertrag für die Planung bereitgestellt.
Das ersetzt weder eine Postfachabfrage noch deren Ergebnis. Unterbrochene oder
unklare Aufrufe werden nicht automatisch wiederholt. Zeitraumfilter richten sich
nach dem wirklichen Schema; grobe Tagesfilter dürfen nicht als exakte lokale
Kalendertagsgrenzen ausgegeben werden. Normale Systemadministration behält ihre
freigegebene Recherche.
