# Projekte und Gespräche endgültig löschen

**Projekt öffnen → Projekt löschen** entfernt den Projektraum, seine Gespräche,
Nachrichten und Laufhistorien, Quellenkopien und Indexdaten, erstellte Dateien samt
Versionen, Projektskills, Rechercheeinträge und zugehörige Antwortvorgaben aus der App.
Archivieren bleibt als separate, reversible Möglichkeit erhalten.

**Gesprächsliste → ⋯ → Gespräch löschen** ist für aktive und archivierte Chats
verfügbar. Im geöffneten Gespräch bleibt der Papierkorb erreichbar; Projektgespräche
lassen sich außerdem in der Projektliste entfernen. Nachrichten, historische Versionen,
Läufe und Gesprächsvorgaben werden gelöscht. Unabhängig gespeicherte Projektdateien,
Erinnerungen und Quellenbelege bereits gespeicherter Dateien bleiben erhalten.

Der Bestätigungsdialog zeigt den Namen und die Anzahl betroffener Inhalte. Abbrechen
und Escape löschen nichts. Erst **Endgültig löschen** sendet den Löschauftrag.
Ein SHA-256-Zustandsnachweis bindet die Bestätigung an die geprüften Daten. Ändern
sich Inhalte zwischen Vorschau und Löschung, verlangt der Dialog eine neue Prüfung.
Projekt-DELETE benötigt diesen Nachweis; bestehende authentifizierte Chat-DELETE-
Aufrufe bleiben kompatibel. Die neue Chatoberfläche sendet ihn ebenfalls.

Aktive Antwort-, Quellen- und Dateierzeugung blockiert eine Löschung bis zum
Abschluss. Dynamische Aufgaben-, Workflow-, Skill- und Vault-Bindungen müssen zuerst
aufgelöst werden. Unabhängige historische Kopien werden erhalten; eine geänderte
aktuelle Aufgabenbindung darf eine Löschung wieder ermöglichen. Externe Originale,
Vault-Dateien, heruntergeladene Exporte und bestehende Sicherungen werden nicht
entfernt. Das inhaltsfreie Kostenbuch bleibt erhalten, damit eine Chatlöschung
verbrauchtes Cloudbudget nicht zurücksetzt.

## Dateibereinigung und Betriebszustand

Die API löscht Datensätze in einer Transaktion und legt bei Projektdateien zugleich
einen dauerhaften Bereinigungsauftrag an. Die bestehenden Source-/Artefaktworker
geben feste UUID-/Versionsmanifeste an ihre isolierten Verarbeiter weiter. Diese
entfernen Ausgabedateien mit ihren vorhandenen Schreibrechten und quittieren den
Auftrag; erst dann entfernen die Worker ihre eigenen Eingabe-/Originalkopien.
Die API erhält keine erweiterten Schreibrechte auf Parser- oder Artefaktergebnisse.

Der Dialog und eine Statusanzeige verfolgen die Bereinigung. Nach erfolgreicher
Datenbanklöschung erfolgt kein zweiter DELETE. Ein Neustart setzt die Bereinigung
fort; Fehler bleiben sichtbar und werden erneut geprüft. Erfolg wird erst nach den
Quittungen und tatsächlicher Entfernung gemeldet. Inhaltsfreie Markierungen und
Quittungen verhindern, dass verspätete Offline-Aufträge Ergebnisse wieder anlegen.
Symlinks und frei übergebene Dateipfade werden nicht verfolgt.

- `GET /api/projects/{id}/deletion` und `GET /api/conversations/{id}/deletion`:
  Vorschau mit `counts`, `blockers`, `preserved`, `expected_state`.
- `DELETE /api/projects/{id}` mit `{expected_state}`; Chat-DELETE analog.
- Antwort: `deleted_project_id`, `deleted_conversation_ids`, optional `cleanup_id`.
- `GET /api/deletions/{id}/status`: `pending` oder `completed`, ggf. generischer Fehler.

Migration0032 speichert Bereinigungsaufträge und entkoppelt historische
Quellenereignisse mit einem inhaltsfreien Beleg. Die Aufgabenhistorie bleibt sichtbar;
ein gelöschtes Quellenereignis kann nicht erneut ausgeführt werden. Ein Downgrade
ist bei ausstehenden Aufträgen oder entkoppelter Ereignishistorie gesperrt. API-/Dateisystem-/PostgreSQL- und Browserprüfungen verwenden
synthetische Daten. VM-Abnahme und releasegebundene Belege stehen in STATUS.
