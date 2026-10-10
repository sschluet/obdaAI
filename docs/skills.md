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

Import unterstützt einzelne `.md`/`.markdown`-Anleitungen mit begrenztem YAML-
Frontmatter sowie das bisherige JSON-Frontmatter. Der Grundaufbau mit `name` und
`description` entspricht der offiziellen
[Claude-Skill-Dokumentation](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills).
ZIP-Pakete, Skripte, Ressourcen, Abhängigkeiten oder fremde Werkzeugrechte werden
nicht ausgeführt oder automatisch übernommen. YAML-Tags, Aliase, zusätzliche
Rechte und unbekannte Metadaten bleiben ungültig. Das ist eine Verwaltung einzelner
Anleitungen, keine vollständige Implementierung ausführbarer Claude-Skillpakete.

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
`*-SKILL.md`, ohne Schlüssel, Toolrechte oder lokale
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
