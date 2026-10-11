# Generische Integrationen und Use Cases

Stand: 11.10.2026. Der Ausbau erfolgt in getrennt überprüfbaren Schritten. Eine
Verbindungsdefinition ist kein Nachweis einer tatsächlich ausgeführten Funktion.

## Gemeinsame Verwaltung

Einstellungen → Integrationen verwaltet beliebig benannte Profile für Home
Assistant (Bearer-API-Token), Paperless-ngx (Token), MCP (Streamable HTTP), UniFi
(API-Key), SMTP-Mail (TLS465/STARTTLS587) und SSH (Benutzer/Passwort oder privater Schlüssel mit optionalem
OpenSSH-Benutzerzertifikat). Für SSH ist zusätzlich der öffentliche Hostschlüssel
vorgesehen. Ein Benutzerzertifikat ersetzt den privaten Schlüssel nicht.

Ein-/Ausschalten, Bearbeiten und Prüfstatus sind getrennt. Zugangsdaten werden mit
dem bestehenden Masterkey verschlüsselt und niemals über die Lese-API ausgegeben.
Ziel-/Authentifizierungsänderungen verwerfen alte Zugangsdaten. Konfigurationen
werden mit einer erwarteten Revision geändert; veraltete Änderungen werden
abgelehnt. Alte MCP-Definitionen bleiben sichtbar und werden nicht automatisch
umgedeutet oder mit neuen Rechten versehen.

Projekte und Aufgaben speichern eine Auswahl. Projektchats können sie erben,
selbst auswählen oder ausschalten. Die globale Deaktivierung entfernt ein Profil
auch aus der wirksamen Auswahl bestehender Zuordnungen. Der Chat-Laufsnapshot
protokolliert die Auswahl ohne Zugangsdaten. Ausgewählte Paperless-Profile sind jetzt tatsächlicher lokaler KI-Kontext.
Projekt-/Chat-/Aufgabenauswahl wird am Laufstart eingefroren, vor Dienst- und
Modellzugriff erneut geprüft und deaktivierte/geänderte Profile werden abgewiesen.
Der vorhandene Aufgabenmanifest bleibt unverändert; ein separater privater
Integrationsbeleg bindet alle Startwege. Projektbezogene Use Cases übernehmen
die Projektbindung; zusätzliche Eingabe- und Bearbeitungsintegrationen sind auch
ohne Projekt auswählbar. Andere Profile führen noch keine allgemeinen KI-Aktionen aus.

## Netzwerk und Paperless

Aktivierte, vom Benutzer konfigurierte Ziele werden mit der betreiberseitig
aktivierten Integrationsrichtlinie automatisch erreichbar. Die eigene VM verwaltet
nur numerisch geprüfte Adressen und Ports in einer separaten Egress-Kette. Keine
Änderung von eingehenden Zugriffen, Fremdsystemen oder globaler Schreibpause.
Home-Assistant-Adressen mit abschließendem Schrägstrich sind gleichwertig; echte
MCP-Endpunktpfade bleiben exakt. HA, Paperless und MCP haben lesende Zugangstests.
SMTP prüft TLS und Anmeldung ohne Versand. Für UniFi und SSH fehlen weiterhin
die Ausführungsadapter.

Paperless: Suche, Seitennavigation, Metadaten/OCR, Originaldownload, private OCR-
Quelle in Projekten und echte lokale Nutzung im KI-Kontext. Keine Paperless-
Schreiboperationen. [Funktionsvertrag und Grenzen](paperless.md).

Use Cases ist ein eigener Bereich in der Hauptnavigation zwischen Projekte und
Aufgaben. Die Übersicht zeigt Anwendungsfälle projektübergreifend; Suche und
Projektfilter helfen bei der Auswahl. Ein neuer Use Case funktioniert auch ohne
Projekt. Der Projektbezug ist optional und lässt sich im Editor hinzufügen,
wechseln oder entfernen. Die Übersicht kennzeichnet eigenständige Use Cases als
„Ohne Projekt“. Suchbare Projektauswahl, Projektfilter und sichtbare Feldtypen
ersetzen die bisherigen Dropdowns. Auswahlfelder zeigen ihre Optionen direkt.
Projektbezogene Definitionen sind weiterhin gespeichert, jedoch nicht mehr als
Projektreiter erreichbar. Frühere Links auf diesen Reiter öffnen den eigenen
Use-Case-Bereich mit dem entsprechenden Projekt.

Neue Definitionen und Bearbeitungen benötigen einen Verarbeitungsprompt. Der
Editor trennt Auftrag/Kontext, Eingabeparameter und Ausgabevorgaben. Dateifelder
werden lokal extrahiert und mit Originalhash/Parserbeleg gespeichert. Formularwerte
oder ein echter KI-Dialog liefern die Parameter; erkannte Angaben bleiben sichtbar
und im Dialog korrigierbar. Das abschließende Ergebnis wird ausdrücklich beauftragt.

KI-Läufe verwenden die bestehende dauerhafte Warteschlange und Provider-/Budget-
Prüfung. Das Ergebnis kann Markdown, eine strukturierte Tabelle, sichere CSV,
echte Excel-Datei oder ein lokales Balkendiagramm sein. Ausgabespalten können aus
der KI-Analyse entstehen und sind nicht auf Eingabefelder beschränkt. Ungültige
Strukturen werden nicht als erfolgreiche Tabellen exportiert; Rohtext bleibt als
Fehler-/Teilantwortbeleg erhalten. Keine Modellprogramme, Formeln oder Werkzeug-
Aktionen werden ausgeführt. Webrecherche und allgemeine Integrationsabfragen im
Use Case über die hier unterstützten Paperless-Quellen hinaus bleiben getrennte
Ausbauschritte. Mailausgabe erfolgt separat nach einer überprüften Vorschau.
[Integrationsphasen, KI-Erstellungsdialog und Mailversand](use-case-integrations.md).

Alte deterministische Vorlagen und gespeicherte Ergebnisse bleiben erhalten.
Bearbeiten erzeugt eine neue KI-Version mit Pflichtprompt; ein KI-Duplikat lässt
die alte Definition unverändert. Projektbezug bleibt optional. Frühere Ergebnisse
behalten ihre ursprünglichen Revisionen. Eigenständige und zuvor gelöste Use Cases
überleben die Löschung eines früheren Projekts. Aktive KI-Läufe blockieren die
Löschung, bis Abbruch/Abschluss erfolgt ist. Globale Verbindungen und externe
Originale bleiben erhalten. Details: [KI Use Cases](ai-use-cases.md).

## Geprüfte Anschlusswege weiterer Dienste

[Recherche mit offiziellen Quellen](integration-services-research.md): Gmail über
OAuth, Proton über Bridge/IMAP, Synology bevorzugt SMB beziehungsweise File Station,
immocloud über dokumentierte Exporte, Amazon abhängig vom Kontotyp, CHECK24 bis zur
Bestätigung einer passenden Schnittstelle über selbst bereitgestellte Dokumente.
Importprofile dürfen nicht als Live-Verbindungen angezeigt werden.
