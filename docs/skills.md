# Skills: persönliche Anleitungen als Dateien

Die **Skill-Bibliothek** ist über Skills in der Hauptnavigation und unter
**Einstellungen → Skills** erreichbar. Karten zeigen Aktivierung, Verwendung,
Geltungsbereich, lokale/Cloud-Nutzung und den Aufruf. Suche, Filter und Vorlagen
helfen beim Einstieg. Der Editor bietet strukturierte Angaben, Markdown-Vorschau
und ein portables Dateiformat; JSON muss nicht von Hand geschrieben werden.

Pro geprüfter Revision stehen drei Verwendungsarten zur Wahl:

- **Immer verwenden:** als Standard in passenden Gesprächen berücksichtigen.
- **Bei Erwähnung:** nur bei einem expliziten Aufruf wie `/text-ueberarbeiten`
  oder `@text-ueberarbeiten` in der aktuellen Benutzernachricht.
- **Nach Stichwort:** bei passenden konfigurierten Stichwörtern; bestehende Skills
  behalten diese frühere Auswahlregel.

**Chat → + → Skill einsetzen** zeigt aktivierte, aktuell geprüfte Skills des
Arbeitsraums und fügt ihren Aufruf in die Nachricht ein. Ein Aufruf übergeht keine
explizite Gesprächseinstellung „Keine Skills“. Der Benutzer kann im Dialog bewusst
wieder die automatische Auswahl einschalten. Eine feste manuelle Gesprächsauswahl
bleibt ebenfalls vorrangig. Mehrdeutige Aufrufnamen erzeugen eine Auswahlfehlermeldung;
URL-, E-Mail- oder Pfadbestandteile gelten nicht als explizite Skillaufrufe.
Höchstens drei Skills dürfen einen Lauf begleiten. Mehr Treffer verlangen eine
gezielte manuelle Auswahl; fremde Projektskills werden abgewiesen.

## Dateien und Prüfung

Import unterstützt einzelne `.md`/`.markdown`-Anleitungen bis 64 KiB sowie
`.zip`- und `.skill`-Pakete bis 20 MiB. Pakete enthalten eine `SKILL.md`,
Referenztexte, Bilder und Office-Vorlagen. Ein Upload wird zunächst als lokaler,
inaktiver Entwurf mit Verwendung **Bei Erwähnung** gespeichert; Cloudfreigabe
bleibt ausgeschaltet. Name, Beschreibung, Anleitung, Abhängigkeiten und enthaltene
Dateien sind vor der Aktivierung sichtbar. YAML-Beschreibungen mit einem
ungeschützten Doppelpunkt können für den Import normalisiert werden; die App
zeigt diese Änderung an und erhält das Originalpaket unverändert.

Die Grundstruktur mit `name` und `description` entspricht der
[Claude-Skill-Dokumentation](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills).
Importierte Inhalte werden als Benutzeranleitungen behandelt und verleihen
keine Werkzeugrechte. Archivpfade, entpackte Größen, Dateianzahl und Office-Inhalte
werden geprüft; verschlüsselte Archive, Pfadtraversierung und Makrodateien werden
abgewiesen. Skripte werden archiviert und können heruntergeladen werden,
**werden jedoch nicht ausgeführt**. Claude-spezifische Werkzeugaufrufe müssen
durch die unterstützte obdaAI-Dateipipeline abgedeckt sein. YAML-Tags und Aliase
bleiben ungültig.

### Vorlagen und Ressourcen

Im Skill-Editor zeigt **Vorlagen & Ressourcen** alle Paketdateien mit Typ und Größe.
Einzeldateien und das unveränderte Originalpaket lassen sich herunterladen.
Downloads sind an Skill-ID, Revision, Dateipfad und SHA-256 gebunden. Änderungen
an der Anleitung behalten die Paketzuordnung; historische Revisionen behalten
ihre ursprünglichen Ressourcen.

Bei der Dateierstellung werden Office-Master aus aktivierten und ausgewählten
Skills tatsächlich als Vorlage verwendet. Die Vorlage und ihre Revision werden
an den Dateientwurf gebunden. Word übernimmt Dokumentstruktur und Formatvorlagen;
PowerPoint nutzt den vorhandenen Master und seine Folienlayouts. Dateien bleiben
zunächst Entwürfe mit Vorschau und werden erst nach Annahme zum Download
freigegeben. Ein Import allein macht fremde Skripte, Makros oder nicht unterstützte
Arbeitsabläufe nicht ausführbar.

Basis- und Gestaltungsskills können gemeinsam gewählt werden. Eine optionale
Gestaltungslinie ersetzt den zugrunde liegenden Präsentationsmaster nicht. Ein
archivierter Altstand sollte deaktiviert bleiben, damit neue Anfragen nicht
versehentlich zwei unterschiedliche Master auswählen. **Bei Erwähnung** oder
aufgabenbezogene Stichwörter verhindern, dass ein Dokument- oder persönlicher
Schreibstil in sachfremden Antworten angewendet wird.

```markdown
---
name: text-ueberarbeiten
description: Texte verständlicher formulieren, wenn ich diesen Skill aufrufe.
---
Bewahre die Aussage. Verbessere Aufbau, Verständlichkeit und Ton.
```

Reines Markdown wird als Entwurf mit einem aus dem Dateinamen abgeleiteten,
editierbaren Titel geöffnet. Import setzt Cloudfreigaben zurück. Der Benutzer
prüft Inhalt, Verwendung und Scope und kann mit **Speichern & aktivieren** die
exakte neue Revision atomar freigeben. **Entwurf speichern** speichert ohne
Aktivierung. Bearbeitung entfernt die bisherige Aktivierung und erzeugt eine
unveränderliche neue Revision. Veraltete Revisionen oder Hashes führen zu 409.
Ungespeicherte Editor- und Rohdateiänderungen bleiben beim Schließen geschützt;
ein ausdrückliches Verwerfen ist erforderlich. Export liefert das portable
`*-SKILL.md`; bei Paketen sind zusätzlich Original und Ressourcen verfügbar, ohne Schlüssel, Toolrechte oder lokale
Projekt-IDs. Import übernimmt keine lokale Aktivierung oder Vertrauensentscheidung.

Skills starten lokal. Die ausdrückliche Option **Diese Anleitung darf auch an das
gewählte Cloudmodell gesendet werden** gilt nur für die geprüfte Skillrevision.
Sie gibt keine anderen privaten Inhalte frei. Der endgültige Providerübergang
prüft weiterhin Gesprächsfreigaben, Labels und gebundene Grants. Ein privater Skill
kann deshalb eine lokale Auto-Antwort bewirken; die Routing-Erklärung macht diese
Begrenzung sichtbar. Anleitungen sind Benutzerkontext und kein ausführbarer Code.

## Verlauf und Entfernen

Jeder neue Lauf hält Skillinhalt, ID, Revision, Hash und Auswahlgrund fest.
Die Laufhistorie zeigt diese Belege. Deaktivierung und neue Versionen beeinflussen
neue Läufe, ohne alte Antworten nachträglich umzudeuten. Deaktivierte/geänderte
manuell ausgewählte Skills verlangen eine neue Auswahl statt stiller Ersatzregeln.

**Entfernen** archiviert nach Bestätigung; bestehende Revisionen und Laufbelege
bleiben erhalten. Migration 0031 ergänzt den Archivzustand und schützt einen
Downgrade bei archivierten Einträgen. Die grundlegende Skillmigration 0013 und ihre
Vertrauens-/Scopesperren bleiben wirksam. API-, Parser-, Auswahl-, Revisions-,
Cloud- und Browserprüfungen verwenden synthetische Dateien. Historische echte
lokale Modelltests sowie neue releasegebundene Abnahmen sind in STATUS dokumentiert.

Der dedizierte Uploadendpunkt `/api/skills/import-package` erhält in den beiden
Nginx-Vorlagen ein eigenes 20-MiB-Limit. Die allgemeine 1-MiB-Grenze und die
separate 40-MiB-Grenze für Projektquellen bleiben bestehen.

Dateiwünsche akzeptieren auch höfliche Infinitivformen wie „Bitte Präsentation
über ein Thema mit acht Folien erstellen“. Die verlangte Folienanzahl wird
als konkrete JSON-Struktur vorgegeben. Ein falscher Modellumfang erhält höchstens
einen lokalen Korrekturversuch innerhalb der gemeinsamen Dateiplanungsfrist (maximal 170 Sekunden);
es werden keine Folien dupliziert oder erfunden. Ein eindeutig fehlgeschriebener
`bulles`-Schlüssel wird als `bullets` übernommen und im Beleg vermerkt;
widersprüchliche Felder bleiben ungültig. Briefvorlagen geben strukturierte
Anrede, Gruß und Unterschrift einmal aus, ohne doppelte abschließende Modellabsätze.
Fehlende Funktionsangaben bleiben sichtbar; die Originalvorlagen bleiben unverändert.


## Native Diagramme und Excel-Berechnungen

Dateientwürfe unterstützen strukturierte, in Office bearbeitbare Grafikdaten.
Für Präsentationen stehen Prozess, Swimlane, Kreislauf, Roadmap, Matrix,
Kennzahlen, Schichten, Vergleich, Punktmatrix, Statusbalken, Botschaften und
native Charts zur Verfügung. Charts unterstützen Säulen, Balken, Linien,
Flächen, Kreis und Ring. Die moderne AVENDIS-Linie verwendet die vorhandenen
Layouts Cover 1 / Empty 1 / End 2, das vorgegebene Raster und die Navy-/Orange-/
Blau-Farben. Das im Skill vorgesehene Arial-Profil eignet sich für Mac-Empfänger.
Zu dichte Inhalte werden abgewiesen, statt Text außerhalb der Folie zu erzeugen.
Spezielle freie SDK-Kompositionen und beliebige importierte Python-Helfer sind
keine ausführbaren Werkzeuge; die Grafiktypen sind feste, geprüfte Adapter.

Excel enthält native Formeln als ausdrücklich markierte Zellen, beispielsweise
`{"formula":"=SUM(B2:B5)"}`. Gewöhnlicher Text, der mit `=` beginnt, bleibt Text.
Die feste Funktionsliste unterstützt unter anderem IF, SUMIFS, COUNTIFS,
SUMPRODUCT, VLOOKUP, INDEX/MATCH und finanzielle Berechnungen. Zellverweise sind
auf die Datenblätter begrenzt; Zirkelbezüge, externe Arbeitsmappen und unbekannte
Funktionen werden abgewiesen. Die Offline-Berechnung übernimmt nur berechnete
Zellwerte zurück in die originale XLSX: Formeln, Charts und Tabellenstile bleiben
erhalten. Nicht berechenbare Formeln erhalten keine erfolgreiche Dateivorschau.

Währungs-/Prozent-/Datumsformate, Tabellenstil, Eingabe-/Formelfarben,
Ergebniszeilen, gelbe Eingabemarkierungen und einklappbare Detailspalten sind
strukturierte Optionen. Balken-, Linien-, Flächen-, Kreis- und XY-Charts bleiben
in Excel editierbar. Der Dateidialog zeigt Formelzellen ausdrücklich und erhält
Grafikdaten, Vorlagenbindung und Berechnungen in Folgeversionen.

Designanleitungen und gehashte Referenztexte werden bei der lokalen Planung als
Gestaltungsvorgaben behandelt. Sie sind keine fachlichen Quellen zum Thema der
Präsentation. Numerische Grafiken brauchen vorgegebene Daten oder ausdrücklich
als synthetisch angeforderte Beispiele.

Bei falschen Grafik-/Formelstrukturen ist höchstens ein lokaler Korrekturversuch
innerhalb der gemeinsamen Zeitgrenze möglich. Er benennt nur Validierungspfade;
ungültige Felder werden nicht still entfernt und Quellenwerte nicht verändert.

XLOOKUP unterstützt genaue Treffer in gleich großen eindimensionalen Bereichen
und einen optionalen Wert für fehlende Treffer. Abweichende Suchmodi sind nicht
freigegeben. Für Calc 7.4 wird nur die separate Berechnungskopie in INDEX/MATCH
übersetzt; die Download-Datei behält die native Excel-Funktion. Chart-Datenreihen
können entweder die Kopfzeile enthalten oder eindeutig als reiner Datenbereich
angegeben werden. Titel beziehen sich weiterhin auf die tatsächliche Kopfzelle.

Roadmaps können benannte Zeiträume mit `from_period` / `to_period` verwenden.
Die Darstellung ordnet sie eindeutig den vorhandenen Spalten zu und trennt
überlappende Aufgaben in Unterzeilen. Es werden keine Datumswerte erfunden.
Dateiplanung verwendet eine eigene Generierungsfrist von maximal 170 Sekunden
innerhalb der konfigurierten Generierungsgrenze, einschließlich höchstens einer
Korrektur; die kürzere Chat-Vorbereitungsfrist wird dafür nicht verwendet.
