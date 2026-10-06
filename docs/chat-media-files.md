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
