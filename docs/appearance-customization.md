# Persönliche Oberfläche

Unter **Einstellungen → Allgemein** lässt sich der Arbeitsraum anpassen:

- **App-Name:** eigener Name im Kopf der Navigation.
- **Anzeigename:** persönlicher Name an der Profilkarte unten links.
- **Profilfoto:** eigenes Bild auswählen oder entfernen.
- **Abstände:** kompakte Ansicht mit weniger Platzverbrauch oder großzügige Ansicht.
- **Akzentfarbe:** Indigo, Blau, Petrol oder Rosé.

Die Auswahl wird serverseitig gespeichert und beim erneuten Öffnen der App
angewendet. Änderungen werden über die Speichern-Aktion bestätigt. Ohne eigene
Angaben bleiben der bisherige App-Name und der neutrale Avatar erhalten.

## Anzeige und KI-Kontext

Diese Angaben gestalten ausschließlich die Oberfläche. Der persönliche
Anzeigename und das Foto werden nicht automatisch als Profilinformationen,
Chatkontext, Suchanfrage oder Routingmerkmal verwendet. Inhaltliche Angaben zur
Person und ihre Freigaben liegen weiterhin unter **Einstellungen → Über mich**.

## Fotoverarbeitung

Die Bildauswahl verarbeitet Rasterbilder im Browser zu einem quadratischen
Avatar mit 256 Pixeln im WebP-Format. Der Server prüft das Ergebnis auf maximal
150 KB und 512 Pixel je Seite und speichert die Rasterdaten ohne Bildmetadaten
neu. SVG, Animationen und beliebige Datei-URLs sind keine Profilfotos. Die
ursprüngliche Datei wird nicht als Originaldokument in das Projekt aufgenommen.

## Auslieferung und öffentliche Beispiele

Für Website-Abbildungen wird ausschließlich eine isolierte synthetische
Testoberfläche mit neutralem Avatar verwendet. Die neue Darstellung ist
implementiert. Die tatsächliche Installation und Abnahme auf der Test-VM sowie
die Veröffentlichung des öffentlichen Showcase müssen separat bestätigt werden.
