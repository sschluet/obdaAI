# M4: lokale Dateierstellung und Versionen

Stand 05.10.2026. M4 bleibt teilweise umgesetzt. Dieser Quellstand ist bis zum
verifizierten Rollout nicht mit dem installierten Stand gleichzusetzen.

| Funktion | Implementiert | Nachweis / verbleibende Grenze |
|---|---|---|
| Word | Editierbarer DOCX-Text, Abschnitte, Tabellen, blaue Gestaltung | Native Datei erneut geöffnet; synthetisches Layout gerendert/visuell geprüft |
| PowerPoint | Editierbare Folien, feste gewünschte Anzahl, Stichpunkte, Notizen | Native Datei erneut geöffnet; zwei synthetische Folien visuell geprüft |
| PDF | Seiten mehrerer gebundener Originale auswählen, umordnen, drehen, weglassen | Auswahl/Rotation getestet; Signatur/Passwort abgewiesen; Kommentare, Formulare, Links entfernt |
| Bilder | Echter Zuschnitt, Größenanpassung, Collage, PNG/JPEG; EXIF entfernt | Pixel-/Formatprüfung und Erhaltung des Originals; keine KI-Bildgenerierung |
| Offline-Runner | Nonroot, netzwerkfrei, readonly Runtime, ohne DB/Secrets/Vault; Landlock pro Auftrag | Eigene Linux-VM: vier Dateien, sechs Vorschaubilder, Replay ohne Überschreiben bestanden |
| Projektoberfläche | Normale Dialoge für alle vier Formate, Vorschau aller Seiten, explizite Freigabe, Download | Synthetischer mobiler Browsercheck bestanden; Vorschauen der UI-Fixture sind ausdrücklich keine Layoutabnahme |
| Versionen | Schema 0020, immutable Vorgaben/Quellhashes, revisionsgebundene Folgeversion, kein Überschreiben | Auth/CSRF/Scope/Quell- und Ausgabedrift/Replay/Review-Gate per API geprüft |
| Dispatch | Queue und Artefaktversion in derselben PG-Transaktion; eigener Worker, Wiederanlauf gleicht Ergebnis ab | Echte PG-Abnahme der Dateiqueue bestanden; vollständiger PG-Gesamtcheck und Live-Rollout noch ausstehend |
| Modell / Chat | Lokale DOCX-/PPTX-Entwürfe aus Ziel und expliziten Quellenauszügen; Folgeänderung bindet konkrete Ausgangsversion; Chatantwort als Word übernehmen | API-/UI-Abnahme synthetisch bestanden; echte lokale Modellabnahme offen. Fakten und Layout benötigen menschliche Prüfung |
| Betrieb | Eigener Compose-Overlay, Speicher-/CPU-/Zeitlimits, Sicherung eigener Dateien und DB vorbereitet | Produktive Installation und verschlüsselter Schema-0020-Restore noch ausstehend |

Eine gültige Datei oder erfolgreiches Rendering ist keine visuelle Freigabe.
Der Status bleibt `needs_review`, bis der angemeldete Nutzer alle Vorschauseiten
der genauen Dateiversion bestätigt. Download ist vorher gesperrt. Neue Versionen
verändern keine Originale und ersetzen keine früheren Ausgaben.

Die isolierte Laufzeit erhält nur feste serverseitige Dateinamen und Kopien der
gebundenen Quellen. Keine Modellskripte, Makros, frei gewählten Pfade oder URLs.
LibreOffice verwendet einen eigenen Unix-Socket-tmpfs; allgemeines `/tmp` bleibt
readonly. Ein normaler Erststart-Reboot von LibreOffice (Status 81) wird genau
einmal mit derselben festen Argumentliste wiederholt. Crash/Fremdfehler werden
nicht wiederholt. Das Verhalten entspricht dem offiziellen
[LibreOffice-Launcher](https://github.com/LibreOffice/core/blob/libreoffice-7.4.7.2/desktop/unx/source/start.c).

Je Auftrag maximal 20 Quellen / 100 MiB, einzelne Quelle 20 MiB, Ausgabe 40 MiB,
Vorschauen insgesamt 100 MiB, gesamte temporäre Ausgabe 220 MiB / 5000 Einträge.
Vier aktive Aufträge, maximal 1000 Versionen und 2 GiB eigener Spool inklusive
320-MiB-Reserve pro Auftrag. Der getrennte Worker blockiert den Chat nicht.

Lokale Entwürfe erhalten maximal vier ausgewählte Quellen mit jeweils zwei
passenden Textauszügen. Verwendete Quellrevisionen, Hashes, Fundstellen, lokale
Providerrevision, Prompt-/Zielhash und Ausgangsversion werden an ein 30 Minuten
gültiges authentifiziertes Entwurfsreceipt gebunden. Die bestätigte Dateiversion
speichert den Beleg samt Kennzeichnung manueller Änderungen. Keine Dateierstellung
beim Entwurf und keine Cloudfreigabe. Falsche Anzahl Folien, unbekannte Schemafelder,
Quelle/Projekt/Provider/Ausgangsversion-/Textdrift werden abgewiesen.

Chatübernahme bindet eine vorhandene aktive Antwort an Gespräch/Revision/Hash und
speichert ihren unveränderten lokalen Herkunftssnapshot. Fremde Projektgespräche
und Vault-Chats sind nicht exportierbar. Manuelle Folgeversionen behalten diesen
Snapshot. Diese Funktion verschiebt keine anderen Gespräche oder Quellen.

Weiter offen: Bilder in DOCX, optionale DOCX→PDF-Ausgabe, PDF-Erstellung aus Text,
Bildbeschriftung, direkte natürliche Chat-Dateiplanung und umfassende Layout-/
semantische Qualitätsabnahme. Die App bietet keine überprüfte echte Schwärzung.
