# M3 Skills: erste Chat-Vertikale

Skills sind Markdown-Dokumente mit JSON-Frontmatter zwischen `---`-Zeilen.
JSON ist ein bewusst begrenzter YAML-Teilumfang; beliebiges YAML, Tags, Aliase,
Code und unbekannte Metadaten werden nicht interpretiert. Das Format lautet:

```markdown
---
{"format":"obdaai-skill-1","name":"Analyse","description":"Befunde ordnen","keywords":["analysiere"]}
---
Nenne Befunde, offene Fragen und nächste Schritte.

Beispiel: Ein Befund mit Quelle und Unsicherheit.
```

Import und Erstellung nutzen denselben Validator und starten deaktiviert. Eine
Bearbeitung erzeugt eine unveränderliche neue Revision und entfernt Vertrauen
und Aktivierung. Erst die menschliche Prüfung des exakten SHA-256 und der Revision
aktiviert den Skill. Export enthält nur das portable Dokument, keine Aktivierung,
Zugänge, Toolrechte oder lokal gültigen Projekt-IDs. Scope wird beim Import gewählt.

Globale und projektgebundene Skills stehen im Chat bereit. Automatisch werden
nur aktivierte, aktuell vertraute Skills mit einem passenden literalem Stichwort
in der letzten Benutzernachricht ausgewählt. Mehr als drei Treffer erfordern eine
manuelle Auswahl. Pro Gespräch kann der Benutzer automatisch, keine Skills oder
bis zu drei explizite Skills wählen. Fremde Projektskills werden abgewiesen.
Deaktivierte/geänderte manuell gewählte Skills stoppen den nächsten Chatlauf mit
409, anstatt still andere Skills zu laden. Auswahländerungen sind vergleichsgebunden
und während eines laufenden Gesprächs gesperrt.

Jeder neue Lauf speichert Dokumentinhalt, Revision, SHA-256 und Auswahlgrund in
seinem unveränderlichen Kontext. Laufhistorie zeigt die geladenen Hashes. Skills
bleiben LOCAL_ONLY und werden als Benutzerkontext verarbeitet. Skilltext und
Metadaten erteilen keine Freigaben; es gibt keinen ausführbaren Code oder Werkzeug-
Dispatcher im Skillpfad. Vorhandene Quellenuploads werden nie als Skills aktiviert.
Spätere Cloud- und Task-Skills brauchen eigene Revisions-/Datenschutzverträge.

Migration 0013 ergänzt Skills/Revisionen und Chat-Auswahl additiv. Downgrade mit
vorhandenen Skills wird zum Schutz der Historie verweigert. API-/Kontrakttests
prüfen Importvertrauen, Hashbindung, Revisionen, Scope, Override, Deaktivierung
und Rechte-/Labelinjektion. A08 mit dem echten lokalen Modell ist bestanden: gleiche synthetische Frage,
Revision 1 Deutsch, Revision 2 Englisch, unterschiedliche Antworten und dokumentierte
Hashes. Skills danach deaktiviert. Ein Tabellenversuch wurde als artifact klassifiziert
und vor Ausführung gestoppt; diese Klassifikation bleibt offen. Skillmutation und
Vault-Abgleich erhalten getrennte PostgreSQL-Sperren; ein echter PG-Test hält die
Vault-Sperre während einer Skill-Erstellung und prüft deren unabhängigen Abschluss.

Offen im gesamten M3: aufgabenbezogene Skills und automatische Auswahl jenseits
expliziter Stichwörter, TaskSpec/Task-Center, externe Adapter und deren Abnahmen.
