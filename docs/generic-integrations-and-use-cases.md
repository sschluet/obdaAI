# Generische Integrationen und Use Cases

Stand: 11.10.2026. Der Ausbau erfolgt in getrennt überprüfbaren Schritten. Eine
Verbindungsdefinition ist kein Nachweis einer tatsächlich ausgeführten Funktion.

## Gemeinsame Verwaltung

Einstellungen → Integrationen verwaltet beliebig benannte Profile für Home
Assistant (Bearer-API-Token), Paperless-ngx (Token), MCP (Streamable HTTP), UniFi
(API-Key) und SSH (Benutzer/Passwort oder privater Schlüssel mit optionalem
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
protokolliert die Auswahl ohne Zugangsdaten. Gespeicherte Auswahl ist zunächst
Metadaten; sie ruft noch kein Werkzeug auf und verspricht keine automatische
Auswertung. Die Oberfläche benennt diese Grenze ausdrücklich.

## Weitere Ausführungsschritte

Der aktuelle MCP-Katalogtest kann nur vorhandene serverseitig freigegebene Ziele
verwenden. Neue Paperless-, UniFi- und SSH-Profile benötigen anschließend ihren
Adapter und reale Abnahme. Arbiträre Shellbefehle oder unbekannte MCP-Schreibrechte
werden nicht aus fremden Beschreibungen übernommen.

1. Gemeinsamer Zielvertrag: exakte Adresse/IP, TLS beziehungsweise SSH-Hostschlüssel,
   begrenzte Antwortgrößen/Zeitbudgets und bestehende Netzwerkreichweite prüfen.
2. Feste Lesefähigkeiten: HA-Entitäten/Status, Paperless-Dokumentensuche,
   UniFi-Sites/Gerätestatus, freigegebene MCP-Schemas und feste SSH-Statusprofile.
3. Auswahl am tatsächlichen Ausführungsrand erneut prüfen; deaktivierte/geänderte
   Verbindungen stoppen den Zugriff. Ergebnisse bleiben LOCAL_ONLY.
4. Projekt- und Aufgabenbindung um Capability/Revisionsdigest ergänzen; Chat
   verwendet nur ausgewählte Fähigkeiten und protokolliert tatsächliche Aufrufe.
5. Änderungen an Drittsystemen separat als konkrete freizugebende Aktionen.

Die neuen Profile verändern keine Firewallregeln, bestehenden HA-/n8n-Dienste,
Vault-/NAS-Freigaben oder globale Schreibpause. Reale Serveradressen werden vom
Benutzer vor Verbindungstests benötigt; Zugangsdaten gehören nur ins lokale UI.

## Eigener Bereich Use Cases

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

Der Editor speichert versionierte Definitionen: Name, Beschreibung,
Formularfelder, Darstellung als Formular oder Frage-/Antwortfolge sowie geordnete
Ausgabespalten. Text, längerer Text, Zahlen, Datum und feste Auswahloptionen werden
validiert. Ergebnisse binden die exakte Definition und Eingabewerte an einen
wiederholbaren Lauf. CSV/Excel und Diagramme verwenden dieselben gespeicherten
Werte; Textvorlagen ersetzen nur definierte Platzhalter.

Diese erste Ausführung ist deterministisch und lokal. Sie erfindet keine Zahlen
und führt weder Modellcode, Tabellenformeln, JavaScript noch SQL aus. Textvorlagen
sind ausdrücklich keine KI-generierte Analyse. KI-Dialoge, automatische Extraktion
aus Quellen, mehrere Arbeitsblätter, berechnete Kennzahlen sowie Integration- und
Task-Ausführung sind weitere Schritte und werden nicht als abgeschlossen beworben.

CSV schützt Textzellen vor Tabellenformeln; XLSX erhält Text als Text und echte
Zahlen als Zahlen. Downloads erfordern eine Anmeldung. Änderungen am Projektbezug
erzeugen eine neue Definition; bereits gespeicherte Ergebnisse behalten ihre
ursprüngliche Revision. Projektlöschung entfernt nur die zu diesem Zeitpunkt
zugeordneten Use-Case-Definitionen, Ergebnisse und Zuordnungen. Eigenständige Use
Cases und zuvor gelöste Zuordnungen bleiben erhalten; globale Verbindungsprofile
und externe Originale bleiben erhalten. Neue Ergebnisse oder Zuordnungen machen
alte Löschvorschauen ungültig.

## Geprüfte Anschlusswege weiterer Dienste

[Recherche mit offiziellen Quellen](integration-services-research.md): Gmail über
OAuth, Proton über Bridge/IMAP, Synology bevorzugt SMB beziehungsweise File Station,
immocloud über dokumentierte Exporte, Amazon abhängig vom Kontotyp, CHECK24 bis zur
Bestätigung einer passenden Schnittstelle über selbst bereitgestellte Dokumente.
Importprofile dürfen nicht als Live-Verbindungen angezeigt werden.
