# Geprüfte lokale Aufgabenabläufe

Der normale Aufgabendialog kann bis zu fünf bekannte Schritte hinzufügen, umordnen
und entfernen. Zur Verfügung stehen Arbeitsraumprüfung, drei feste lesende
Home-Assistant-Berichte und eine abschließende lokale Auswertung. Es werden keine
freien URLs, Nodes, SQL-Abfragen oder Modellskripte erzeugt. Schreibprofile behalten
ihre separate konkrete Aktionsfreigabe.

Systemberichte gelangen nur bei einer ausdrücklich gespeicherten
`include_system_reports`-Auswahl in den lokalen Modellkontext. Das Dialogfeld benennt
die Datenweitergabe ausdrücklich. Natürliche Entwürfe müssen eine HA-Auswertung
im direkten Nutzerziel verlangen; ein Modellvorschlag allein gibt sie nicht frei.
Jeder Bericht besitzt einen dauerhaften Leseschrittbeleg. Während Netzwerk-I/O wird
keine globale Aufgaben-DB-Sperre gehalten. Pause, Abbruch, Vorgaben-/Kontrollrevision,
Zeitplan und Quellen werden vor und nach dem Lesen erneut geprüft. Ein unterbrochener
laufender Modellauftrag wird nicht automatisch wiederholt.

Die feste Bedingung „nur bei verfügbaren HA-Updates“ wird ausschließlich aus den
konkreten lesenden HA-Belegen lokal ausgewertet. Bei null Updates wird die Auswertung
mit einem sichtbaren Überspringbeleg abgeschlossen, ohne Modellaufruf. Unbekannter
Updatezustand gilt nicht als Nachweis fehlender Updates und hält die Ausführung an.
Berichte, Dokumente, Modellprompt und Antwort bleiben LOCAL_ONLY; Kosten sind null.

Das Workflowfenster zeigt den gespeicherten geprüften Ablauf mit Kanten und
Schritttypen. Die n8n-Vorlage delegiert weiterhin den gesamten revisionsgebundenen
lokalen Ablauf an denselben Aufgaben-Gateway; n8n erhält nur technische Auftrags-/
Ausführungsidentitäten. Das ist keine freie n8n-Nodegenerierung und keine parallele
DAG-Ausführung. Unveränderte alte Aufgaben behalten ihre kanonische JSON-Form und
Hashbindung, weil abwesende Zusatzoptionen nicht neu serialisiert werden.

## Geprüfter n8n-Abschlussgraph

Die explizite Aufgabenoption `workflow_wait` erzeugt zusätzlich einen achtknotigen
n8n-Graph: authentifizierter Start, gebundener Gateway, Statusabfrage, Abschluss-
Bedingung, begrenztes Warten, Erfolgsbedingung, Abschluss oder fester Fehlerstopp.
Alle Nodes, Versionen, URLs, Ausdrücke, Credentials und Kanten sind code-owned und
werden gegen die exakte veröffentlichte Version geprüft. Der Graph enthält keinen
Zieltext und keine Quellen-/Berichtsdaten. Statusrückfragen authentifizieren dieselbe
Bindung und dieselbe Execution-ID; nach Pause oder Revisiondrift werden sie gestoppt.

Die Schleife fragt ausschließlich Betriebsmetadaten ab und startet keinen zweiten
TaskRun. Der Graph hat 180 Sekunden Gesamtgrenze. Bei längerem lokalen Lauf liefert
nur der vorhandene Laufbeleg den tatsächlichen Ausgang; kein zweiter Webhook-POST.
Alte zweiknotige Workflows bleiben unverändert. Neue Einrichtung und Veröffentlichung
verwenden weiterhin eigene konkrete Aktionsfreigaben. Unbekannte Nodes, frei
formulierter Code und fremde Credential-/Zielbindungen sind ausgeschlossen.

Geprüfte Primärquellen für n8n 2.7.5:
- [If-V2](https://github.com/n8n-io/n8n/blob/n8n%402.7.5/packages/nodes-base/nodes/If/V2/IfV2.node.ts)
- [Wait](https://github.com/n8n-io/n8n/blob/n8n%402.7.5/packages/nodes-base/nodes/Wait/Wait.node.ts)
- [Stop and Error](https://github.com/n8n-io/n8n/blob/n8n%402.7.5/packages/nodes-base/nodes/StopAndError/StopAndError.node.ts)
