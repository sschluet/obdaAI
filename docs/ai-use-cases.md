# Use Cases als wiederverwendbare KI-Aufträge

Ein Use Case beschreibt eine wiederholbare Aufgabe für die KI. Die definierten
Eingaben und das Ergebnisformat geben dem Auftrag eine klare Struktur; der
Verarbeitungsprompt legt fest, was die KI mit den Eingaben tun soll. Ein Projekt
bleibt optional. Ein Formular allein ist noch kein KI-Auftrag.

## Einen Auftrag definieren

1. Name, Zweck und optionalen Projektbezug festlegen.
2. Einen verbindlichen Verarbeitungsprompt schreiben: Ziel, Rolle, gewünschte
   Bearbeitung und Umgang mit fehlenden Angaben beschreiben.
3. Die abzufragenden Parameter definieren. Text, Zahlen, Datum, Auswahl und
   Eingabedateien können unterschiedliche Informationen liefern.
4. Formular oder KI-geführten Dialog auswählen.
5. Die gewünschte Ausgabe unabhängig von den Eingabefeldern definieren: Bericht,
   Tabelle, CSV, Excel oder Diagramm. Ausgabespalten können beispielsweise aus
   der Analyse einer Datei entstehen und müssen keine kopierten Eingabewerte sein.

Ein Beispielprompt für einen fiktiven Servicebericht:

> Analysiere die bereitgestellten Servicekennzahlen für den angegebenen Zeitraum.
> Erläutere Auffälligkeiten und schlage konkrete Verbesserungen vor. Unterscheide
> belegte Werte von Annahmen. Fehlen notwendige Angaben, frage gezielt nach.
> Verwende ausschließlich die bereitgestellten Daten; erfinde keine Kennzahlen.

## Eingaben und Ergebnisse

Das Formular sammelt die Parameter und angehängten Dateien für einen konkreten
Auftrag. Im Dialogmodus stellt die KI Rückfragen anhand des Auftrags und der noch
fehlenden Angaben. Antworten gehören zur jeweiligen Dialogsitzung und ersetzen
keine Definition. Die erfassten Werte sollen vor der Ergebniserstellung überprüfbar
bleiben. Eine Dateiauswertung braucht lesbaren extrahierten Inhalt; ein Dateiname
allein genügt nicht. Fehlgeschlagene Extraktion darf nicht als verarbeitete Datei
erscheinen.

Die Verarbeitung verwendet einen eingefrorenen Stand der Definition, Eingaben
und Dateibelege. Änderungen am Use Case verändern frühere Ergebnisse nicht.
Tabellen und Exporte benötigen ein validiertes Ergebnis in der definierten
Struktur; Modelltext oder ein abgebrochenes JSON ist keine erfolgreiche Tabelle.
Textausgaben behalten die tatsächliche Modellherkunft und den Laufstatus.

## Ausführung und Grenzen

KI-Aufträge verwenden die vorhandene dauerhafte Warteschlange, Providerprüfung,
Kontext- und Kostenlimits. Datei- und Projektinhalte bleiben privat und dürfen
nicht durch die Modellwahl automatisch für Cloud freigegeben werden. Eine
Cloud-Auswahl muss gesperrte private Inhalte erklären statt unbemerkt lokal zu
antworten. Aus Datei- oder Modellinhalten werden keine ausführbaren Programme,
Makros, Shellbefehle oder externen Aktionen erzeugt.

Vorhandene ältere Use Cases und ihre gespeicherten Ergebnisse bleiben erhalten.
Die bisherige deterministische Formularverarbeitung wird als solche kenntlich
gemacht. Neue KI-Aufträge benötigen den Verarbeitungsprompt. Allgemeine
Integrationsausführung, Webrecherche und beliebige Dashboardprogramme sind
separate Fähigkeiten und dürfen nicht allein aus einer Use-Case-Definition
abgeleitet werden.

Diese Seite beschreibt den Funktionsvertrag; den tatsächlich geprüften und
installierten Stand dokumentiert [STATUS](../STATUS.md).
