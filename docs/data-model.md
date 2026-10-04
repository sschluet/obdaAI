# Datenmodell

Alle Zeitpunkte UTC; UI-Zeitpläne Europe/Berlin. UUIDs als stabile IDs. Persönliche
Daten liegen ausschließlich in Runtime-Volumes/DB, nie in Git.

| Aggregate | Felder / Regeln | Einführung |
|---|---|---|
| Session | Tokenhash, CSRF, Ablauf; kein Klartexttoken in DB | M1 |
| Conversation / Message | Titel, manuell gesetzt, Projekt, archiviert, Rolle, Label, Revision, Inhalt | M1 |
| Provider / Model | Typ, geprüfte Origin, Secretref, Fähigkeiten, Limits, Budgets, Labels | M1/M5 |
| Run / RunEvent | Zustand, Modell, Routinggrund, Quellen/Skills-Revisionen, Kosten nullable, Abbruch, Idempotenz | M1/M3 |
| Project / Source / Chunk | Scope, Label, Hash, unverändertes Original, Extraktion, Seite/Folie/Zellbereich | M2 |
| Memory / MemoryRevision | Vault-ID, Scope, Label, Hash, base revision, tombstone, Konflikt | M2 |
| Connection / Tool | Transport, Ziele, Parametermodell, Rechte, Timeout, Audit | M3 |
| Skill / SkillRevision | Markdown, Frontmatter, Beispiele, Scope, Fähigkeiten, Vertrauensstatus | M3 |
| Task / TaskRevision | Ziel, Zeitplan, Grenzen, Kriterien, n8n-ID/Revision, Zustand | M3 |
| Approval / ActionReceipt | Aktionshash, Scope, expiry, revoke, Idempotenz, unbekannter Ausgang | M3 |
| Artifact / ArtifactVersion | Quelle, Plan, Datei/Hash, Vorschau, QA, Vorgängerversion | M4 |

PostgreSQL App-Schema mit Alembic; n8n separate Datenbank und Rolle. Queue-Schema
nur über Procrastinate-Migrationen. Keine direkte n8n-Datenbankmanipulation.
Memory-Markdown ist kanonisch; Index rekonstruierbar. Umbenennungen/Löschungen
führen zu expliziten Reconciliation-Zuständen, keine Wiederbelebung aus alten Chunks.
