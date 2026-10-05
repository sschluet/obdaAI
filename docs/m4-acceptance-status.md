# M4: Artefakte – aktueller Abnahmestand

M4 ist noch nicht vollständig umgesetzt. Dieser Stand ergänzt die echte lokale
Datei-Erzeugung; er ist noch keine verfügbare Chat- oder Projektraumfunktion.

| Teil | Umsetzung | Nachweis / noch offen |
|---|---|---|
| Word | Editierbare Absätze, Überschriften, Tabellen, native DOCX | Dateiprüfung und synthetische visuelle Vorschau lokal bestanden |
| PowerPoint | Native editierbare Folien und Sprechernotizen, exakt angegebene Folienzahl | Dateiprüfung und alle synthetischen Folien lokal visuell geprüft |
| PDF | Seiten wählen, umordnen, entfernen, kombinieren und drehen | Originalhash unverändert; aktive Katalogaktionen nicht übernommen; signierte/verschlüsselte Eingaben abgewiesen |
| Bilder | Echter Zuschnitt, Größenanpassung, Collage, PNG/JPEG, EXIF entfernt | Pixelbasierte Prüfungen; keine KI-Bildgenerierung |
| Vorschauen | Offline LibreOffice/Poppler bzw. Bildvorschau | Rendern beweist keine visuelle Freigabe: Ausgabe bleibt needs_review |
| Isolation | Separater nonroot Container ohne Netzwerk/DB/Secrets/Vault; genau eine Requestbindung per Landlock-Kindprozess | Linux-Containerabnahme in CI ergänzt; Live-Runner noch nicht installiert |
| Integrität | Strikte Datenpläne, feste serverseitige Dateinamen, Quellhashprüfung, unveränderte Originale, kein Überschreiben | Unitprüfungen; dauerhafte Anwendungsversionen/Projektbindungen noch offen |
| Anwendung | Noch nicht angebunden | Authentifizierte API, SQL-Versionen, Queue/Reconciliation, Projekt-/Chat-Dialog, Downloads und Freigaben fehlen |
| Modell | Noch nicht angebunden | Lokaler strukturierter Plan aus Chat, Quellenbelege, semantische Qualitätsprüfung, Folgeänderungen fehlen |

Der Runner führt kein Modellskript aus. Generierte Titel werden niemals als Pfad
verwendet. Er erhält ausschließlich Kopien gebundener Quellen. Bei abgebrochenem
Render bleibt die Ausgabe fehlgeschlagen; Wiederholung überschreibt keine Version.
Office-Erstellung nutzt die vorhandenen gelockten Bibliotheken python-docx und
python-pptx; PDF und Bilder nutzen pypdf/Pillow. Es gibt keine Cloudübertragung.

Produktiver Betrieb benötigt den eigenen Artifact-Compose-Overlay, private Request-
und Ergebnisverzeichnisse sowie die noch offene API-/Queue-Anbindung. Dieser Stand
ändert den produktiven Compose-Aufbau nicht automatisch.
