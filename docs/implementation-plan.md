# Umsetzung

| Meilenstein | Vertikale Lieferung | Abnahme | Stand |
|---|---|---|---|
| M0 | Bestand, Repo, Architektur, Security-/Datenmodell, CI, Lockfiles | sichere reproduzierbare Basis | implementiert/gepusht; CI grün |
| M1 | Login, persistenter Streaming-Chat, AUTO lokal/OpenRouter, Titel/Historie, Policies | A01-A04/A13 | implementiert und echte lokale/OpenRouter-Abnahme bestanden, siehe STATUS |
| M2 | Projekte, Uploads, Fundstellen, Web, Obsidian/Memory | A05/A09 | abgenommen: CI grün, echte Dateipipeline/Quellenchat/Web/Vault/Sync/Restart und isolierter Restore, siehe STATUS |
| M3 | Werkzeuge, MCP/REST/Browser, Skills, Freigaben, n8n/Task-Center, HA-Grenzen | A08/A10-A12 | in Entwicklung: Skills, Gateway/Freigaben, lokale Modellaufgaben, n8n-Zeitplanung und echte Vorlagenworkflows live; begrenzte MCP-Leseaufrufe, passive Browserprüfung und HA-Berichtsaufgaben implementiert; interaktiver Browser, weitergehende Aktionsprofile und sichere HA-Wartung noch offen |
| M4 | DOCX/PPTX/PDF/Bilder, echte Vorschau, QA, Versionen | A06/A07 | teilweise: vier native Formate live, lokale Modellplanung und Versionen geprüft; breite semantische/Layout-QA offen |
| M5 | OpenAI/Anthropic, mobile E2E, Last, Backup/Restore, Zieldeployment | alle + A14 | teilweise: eigene VM installiert, native Anbieter vorbereitet, mobile Checks und HTTPS-Leseprüfung bestanden; native Livezugänge, Vollast und Fremdsystem-Restore offen |

Reihenfolge nicht durch Pflichtfeatures umgehen. Jede Lieferung: Tests, Diff/Secrets,
Dokumentation, Commit, Push, PR. Fehlender externer Zugang blockiert unabhängige
Implementierung nicht. Tests mit Mocks sind keine Live-Abnahme.

M1: Login und DB-Migration zuerst; lokale JSON-Routingantwort einschließlich einfacher
Antwort im selben Aufruf. Fähigkeiten als Liste, Modellklasse getrennt. Ein Schemafehler
höchstens einmal reparieren, dann sicher abbrechen; kein heimlicher externer Wechsel.
Historie/Scope/Labels am finalen Gateway prüfen. Streaming-/Abbruchzustand persistieren.
Titel via Queue lokal, manuelle Titel unangetastet. M2 setzt auf diesen Vertrag auf.
