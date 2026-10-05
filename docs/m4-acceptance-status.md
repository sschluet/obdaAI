# M4: lokale Dateierstellung und Versionen

Stand 06.10.2026, produktiv `6fbfb0e` / Schema 0021. Die Dateipipeline ist live;
M4 bleibt wegen weiterer natürlicher Änderungen und breiter Qualitätsabnahme teilweise.

| Funktion | Implementiert und tatsächlich geprüft | Verbleibende Grenze |
|---|---|---|
| Word | Native editierbare Abschnitte/Tabellen/Bilder, blaue Gestaltung, optionaler PDF-Export; Linux-Vorschau, visuelle QA, authentifizierter Download, erneut geöffnet | Allgemeine semantische und Layoutprüfung jeder Nutzerdatei |
| PowerPoint | Native Texte, feste Folienanzahl, Notizen, feste Fonts mit Mindestgrößen und Platzreserve; zwei dichte deutsche Folien visuell geprüft und erneut geöffnet | Breiter Inhalt-/Layoutkorpus; quellengebundene Einzelfolien im Dateidialog |
| PDF | Gebundene Seiten auswählen, umordnen, drehen, weglassen; neue PDFs aus Text/Tabellen/Bildern, Word-PDF-Export; Live-Vorschau/Hashdownload | Keine überprüfte echte Schwärzung; verschlüsselte/signierte Eingaben abgewiesen |
| Bilder | Zuschnitt, Größenanpassung, Collage, PNG/JPEG, Unicode-Beschriftung; echte Pixel-/Live-QA; Alpha-Erhaltung in Word und Komposition auf Collagehintergrund | Keine KI-Bildgenerierung; weitere natürliche Bildänderungen |
| Quellen | Nur gebundene Originalrevisionen/Hashes; explizite Projektsammlung mit 1–4 fertig eingelesenen Originalen; Fundstellen im lokalen Modellplan | Keine automatische Mischung mit fremden Projekten, Memory oder Webrecherche |
| Modell / Chat | Echte lokale Ein-Abschnitt-Datei ohne Quellen und Quellenbericht aus Projektunterlagen bestanden; belegte Farbe und Anzahl korrekt; native Vorschau/Download/Editierbarkeit sowie Word-/gezielte PPTX-Folgeversion live geprüft | Ein erfolgreicher synthetischer Bericht beweist keine allgemeine Faktentreue |
| Versionen | Immutable Vorgaben/Ausgaben/Quellhashes, revisionsgebundene Folgeversionen, alte Word-Datei unverändert | Jede neue Ausgabe benötigt ihre eigene Vorschauprüfung |
| Offline-Runner | Linux nonroot/netzlos/readonly, kein DB-/Secret-/Vaultzugang, Landlock und Ressourcenlimits; fünf Pläne/sieben Vorschauen, PDF-Export und Alpha/Metadatenprüfung bestanden | Kein fremder Code, Macro, Pfad oder URL ausführbar |
| Dispatch / Betrieb | Gemeinsame PG-Transaktion für Version/Queue; dauerhafter Worker, Chat hat begrenzte readonly Spoolmounts; zehn echte PG-Fälle; verschlüsselter isolierter Restore mit 23 Versionen | Keine vollständige V1-/Fremdsystem-Restorebehauptung |

Download bleibt gesperrt, bis alle Vorschauseiten der exakten Version bestätigt
wurden. Gültiges Rendering ist keine visuelle Freigabe. Originale, frühere Versionen
und ihre geprüften Hashes werden nicht überschrieben. Die eigenen synthetischen
Abnahmeprojekte sind wiederherstellbar archiviert; die Originale bleiben erhalten.

Lokale Entwürfe erhalten maximal vier explizite Quellen mit je zwei Textauszügen.
Quellrevisionen, SHA, Fundstellen, Providerrevision, Ziel-/Prompt-/Rohantwortsha und
Ausgangsversion werden an ein authentifiziertes 30-Minuten-Receipt gebunden.
Bestätigte Versionen speichern den Beleg und manuelle Änderungen. Nur ein voller
JSON-Codeblock und genau eine zusätzliche Endklammer sind als protokollierte
Formatnormalisierung zulässig; doppelte Felder, freie Prosa, Zusatzobjekte und Rechte
werden abgewiesen. Ein Schemafehler führt zu einem terminalen gespeicherten Run,
auch wenn seine Meldung länger als die 240-Zeichen-DB-Spalte ist. Kein Modellretry.

Natürliche Dateiwünsche binden neueste Nutzerfrage, Nachrichtrevision/SHA, Gespräch,
Projekt, Quellen und Provider am letzten Schreibpunkt. Abbruch, neue Frage, Archiv
oder Drift erzeugen keine Datei. „Aus den Projektunterlagen“ ist eine ausdrückliche
Quellenauswahl; größere/unvollständige Sammlungen brauchen eine Auswahl im normalen
Dialog. Projekt-/Vault-Historie und Webrecherche werden nicht implizit übernommen.
Chatübernahme und manuelle Folgeversionen behalten ihren unveränderten Herkunftsbeleg.

Je Auftrag: 20 Quellen / 100 MiB, einzelne Quelle 20 MiB, Ausgabe 40 MiB,
Vorschauen 100 MiB, temporäre Ausgabe 220 MiB / 5000 Einträge. Vier aktive Aufträge,
1000 Versionen und 2 GiB Spool mit 320-MiB-Reserve. LibreOffice verwendet privaten
Unix-Socket-tmpfs, allgemeines /tmp readonly. Status 81 beim Erststart wird genau
einmal mit denselben festen Argumenten wiederholt; sonst keine Crashwiederholung.
Siehe [offiziellen LibreOffice-Launcher](https://github.com/LibreOffice/core/blob/libreoffice-7.4.7.2/desktop/unx/source/start.c).

Noch offen: natürliche PDF-Seiten-/Collageoperationen im Chat, komplexere bzw.
dateiübergreifende Änderungen, quellengebundene Einzelfolien, kombinierte
Recherche-Dateierstellung und breitere semantische/Layout-QA. Die normalen Dialoge unterstützen die genannten manuellen Operationen
bereits. Konkrete Folgeänderungen der letzten Chat-Datei sind umgesetzt; siehe
docs/chat-file-revisions.md. Keine vollständige M4-Abnahme aus Unit- oder
Fixturetests ableiten.
