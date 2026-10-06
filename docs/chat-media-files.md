# Lokale Seiten- und Bildoperationen aus dem Chat

Der direkte Nutzerauftrag kann hochgeladene Originale dieses Projektraums anhand
ihres exakten Dateinamens auswählen. Gleichnamige oder noch nicht fertig eingelesene
Originale werden nicht geraten. Namen anderer Räume, Dateipfade und Teilnamen wählen
keine Quelle. Reine Fragen sind kein Dateiänderungsauftrag. Beispiele:

- „Erstelle aus Beleg.pdf eine PDF mit Seiten 3, 1 und drehe Seite 3 um 90 Grad.“
- „Führe eins.pdf und zwei.pdf zu einer PDF zusammen.“
- „Schneide foto.png auf die rechte Hälfte und skaliere auf 128 mal 128 Pixel.“
- „Erstelle eine Collage aus links.png und rechts.png mit zwei Spalten.“
- „Verkleinere die letzte Datei auf 128 mal 128 Pixel.“

Das lokale Modell liefert einen streng validierten Datenplan. Physische Operationen
verwenden nur Metadaten der ausdrücklich gebundenen Originale, nicht OCR-/Dokumenttext
als Steueranweisung. Quelle, Revision, SHA, Gespräch und exakter Nutzerauftrag werden
am letzten Schreibpunkt erneut geprüft. PDF-Seitenpläne können weder mit neuem Text
ersetzt werden noch fremde Originale wählen. Bildpläne erlauben nur normierte
Zuschnitte, feste Größen und PNG/JPEG. Es wird kein Modellcode ausgeführt.

Der normale Dateidialog unterstützt lokale Entwürfe für die gleiche Seiten-/Bildlogik.
Dort sind Quellen ausdrücklich zu wählen; die erzeugten Felder bleiben bearbeitbar.
Die ursprünglichen Dateien und alten Ausgaben werden nicht überschrieben.
Download bleibt bis zur visuellen Prüfung der Vorschauen gesperrt.

Eine einzelne quellengebundene PowerPoint-Folie kann aus einem gebundenen aktuellen
Chat-Artefakt überarbeitet werden. Titel, Anzahl, alle anderen Folien einschließlich
Notizen werden exakt verglichen. Neue Quellenhinweise erscheinen nur auf der
gewählten Folie. Derselbe Vergleich gilt erneut beim Speichern des Entwurfs; eine
ungewollte Änderung anderer Folien wird vor einer neuen Version gestoppt.

Grenzen: bis zu zwanzig benannte Originale für physische Operationen, hundert
Ausgabeseiten, zwölf Bildkacheln und 24 Millionen Ausgabepixel; Inhaltsentwürfe nutzen
höchstens vier Quellen mit begrenzten Auszügen. Die echte Zahl verfügbarer PDF-Seiten
prüft der Offline-Runner; Metadaten aus Textfundstellen sind kein vollständiger
Seitennachweis. Ein Auftrag liefert eine neue Datei, keine behauptete Mehrdatei-
Aufteilung. Keine echte Schwärzung, KI-Bildgenerierung oder semantische Abnahme aus
bloßem Rendering ableiten. Livebelege werden getrennt von Fixturetests dokumentiert.

Bilder ohne OCR-Text und leere PDF-Seiten behalten verifizierte technische
Metadaten als lokale Fundstelle. Das ist keine Bildinterpretation. Der Parser läuft
weiterhin isoliert; Originale bleiben erhalten. Ein beim echten Modell beobachteter
Indexfehler wird nur dann protokolliert normalisiert, wenn genau ein Original
gebunden ist und alle Auswahlindizes exakt 1 lauten: daraus wird Index 0. Mehrere
Originale oder andere ungültige Indizes bleiben strikt, damit keine falsche Datei
unterstellt wird.

Bei genau einem gebundenen Original wählt das Modell keine Quelldatei: der Server
setzt fehlende Auswahlfelder auf diese einzige Originalbindung. Eindeutige direkte
Nutzerangaben wie „Seiten 2,1“, „zuerst Originalseite 2, danach Originalseite 1“,
„erste Ausgabeseite um 90 Grad“ oder „rechte Hälfte auf 128 mal 128 Pixel“ werden
zusätzlich als feste Datenvorgaben geparst. Sie überschreiben widersprechende
Modellvorschläge und stehen mit ihrer Version im `command_binding`-Beleg. Freie
Prosa, unbekannte Geometrie oder mehrere Originale werden nicht so geraten.


PDF-Aufteilung: Im normalen Seitendialog können Trennstellen zwischen Ausgabeseiten
markiert werden, oder jede ausgewählte Seite wird eine eigene PDF. Maximal zwanzig
Teile und insgesamt hundert Ausgabeseiten; Auswahl, Reihenfolge und Drehung gelten
vor der Aufteilung. Downloads enthalten einzeln hashgebundene PDFs und ein ZIP
mit genau denselben unverpackten Teildateien, festen Namen und ohne Pfadübernahme.
Die gemeinsame Vorschau zeigt alle Teile in Ausgabereihenfolge und nennt den Teil.
Erst die Prüfung sämtlicher Seiten schaltet alle Downloads frei. Beschädigte Teile
oder ZIPs sperren die gesamte Version. Originale werden nicht überschrieben.

Natürlicher direkter Auftrag, beispielsweise „Teile Bericht.pdf mit Seiten 3,1,2
in Einzel-PDFs“, bindet die genannte Seitenfolge und die Trennstellen unabhängig
von einem abweichenden Modellvorschlag. „Trenne nach Ausgabeseiten 1 und 3“ erlaubt
konkrete Gruppen. Inhaltsabhängige automatische Kapiteltrennung wird nicht behauptet.
