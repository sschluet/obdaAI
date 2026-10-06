# Längere Textquellen

TXT und Markdown behalten Originalbytes und SHA unverändert. Kleine Dateien mit
höchstens 2000 Zeilen behalten ihre bisherigen Einzelzeilen-Fundstellen. Größere
Dateien werden in zusammenhängende Fenster von normalerweise höchstens 1600 Zeichen
aufgeteilt. Jede Fundstelle benennt die exakten Anfangs-/Endzeilen; neue Markdown-
Überschriften beginnen ein neues Fenster. Einzelne sehr lange Zeilen bleiben erhalten
und unterliegen weiterhin der Gesamttextgrenze.

Die Gesamtgrenze bleibt 800.000 Zeichen und höchstens 2000 extrahierte Einheiten.
Es werden keine Zeilen stillschweigend abgeschnitten. Die Tests vergleichen den
vollständig wieder zusammengesetzten Text und prüfen Überschriften-/Fundstellen-
Grenzen und die weiterhin aktive Zeichenbegrenzung. Der isolierte Parser behält
seine bestehenden Netzwerk-, Dateisystem- und Ressourcenlimits.
