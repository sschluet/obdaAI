# Verbindlicher Umfang und Abnahmematrix

Normalisierte Anforderungen des Entwicklungsauftrags vom 04.10.2026. Alle 19
Abschnitte bleiben Pflichtumfang; M0 ist keine vollständige V1. Persönliche
Betriebsidentifikatoren werden nicht in dieses Repository exportiert.

| Abschnitt | Thema | Meilenstein | Abnahme | Verbindlicher Umfang |
|---|---|---|---|---|
| R01 | Produkt / V1 | M1-M5 | A01-A14 | AUTO, Projekte, Artefakte, Einstellungen, Skills, Wissen, Aufgaben; keine V1-Pflicht still verschieben |
| R02 | Bestand / Betriebsziel | M0/M5 | A13/A14 | Eigene Linux-VM, Inference Mac mini, bestehende Dienste erhalten; n8n/Sync inventarisieren |
| R03 | Architektur | M0/M1/M3 | A10/A13 | React statisch, FastAPI/SQLAlchemy/Alembic/PostgreSQL, Worker persistent, n8n alleinige Terminierung |
| R04 | GitHub | M0-M5 | A14 | Privates eigenes Repo, korrekter Owner, Branch/PR, Commit/Push pro Lieferung, CI/Locks/Secrets |
| R05 | UI / Historie | M1/M5 | A13 | Streaming, Markdown/Code/Tabellen/Copy, Anhänge, edit/retry/cancel, Titel lokal async, Suche/Archiv/Löschen, Quellen/Status, mobile/light/dark/keyboard |
| R06 | Routing | M1 | A01/A02/A04 | Lokale Erstinterpretation, Fähigkeitenliste getrennt von Modell; Kontext, schema/reparatur, Inlineantwort, Limits/Datensatz |
| R07 | Datenschutz | M0-M5 | A03/A04 | Labels an Quellen/Projekten/Dateien/Memory/Runs und Ableitungen, finaler Payloadcheck; kein Cloudfallback |
| R08 | Provider / Einstellungen | M1/M5 | A02/A03/A04 | Local/OpenRouter, direkte OpenAI/Anthropic, zusätzliche kompatible Provider per UI; Fähigkeiten/Tests/Limits/Budget/Secrets/Revisionen |
| R09 | Web / Systeme | M2/M3 | A03/A05/A12 | Toolkatalog, MCP aktuelle Transporte/Auth, begrenzte REST-Adapter, austauschbare echte Suche mit URL/Zeit, Browserallowlist/2FA |
| R10 | Projekte / Quellen | M2 | A05 | Scopeisolation, DOCX/PPTX/PDF/CSV/XLSX/MD/TXT/Bilder, immutable/hash, async extraction, Fundstellen, lokale OCR, strukturierte Rechnungen, sichere Limits |
| R11 | Artefakte | M4 | A06/A07 | Editierbares DOCX/PPTX, PDF-Operationen, echte Bildcollage/crop/resize/export; Plan/Validation/Preview/QA/Version; isolierter Runner |
| R12 | Skills | M3 | A08 | Markdown/frontmatter, import/export/versions/examples/scope/trust, automatisch gezielt wählen, geladene Version auditieren; keine Rechteausweitung |
| R13 | Obsidian | M2 | A09 | Bestehender Sync, Vault kanonisch, readonly allgemein, begrenzte Memorywrites, IDs/hash/revision/tombstone/conflict/atomic/debounce/reconcile |
| R14 | n8n | M3 | A10/A11 | TaskSpec, expliziter Zeitplan/Autonomie, geprüfte Nodes/API/Graph/Credentials/Ziele, draft/test/approval/activate/drift; same privacy/action gateway |
| R15 | Task-Center | M3/M5 | A10/A11/A13 | create/edit/pause/resume/run/cancel/archive, next/last/detail, persistente Runs/Approval, UTC/DST/limits/retry/missed schedule/idempotency/uncertain state/globalpause |
| R16 | Autonomie / HA | M3 | A12 | Analyse/einzelfreigabe/begrenzt autonom; action/revision/expiry; Installation erkennen, Backup abgeschlossen/integrity/restore geprüft, Versions-/Entitätsgrenzen, kein Selfdeploy |
| R17 | Sicherheit / Betrieb | M0-M5 | A03/A14 | Login/sessions/CSRF/rate, Secrets, injection/SSRF/path/symlink, nonroot/no socket/limits/TLS/firewall, Priorität, rotation, tested backups |
| R18 | Tests / Messung | M0-M5 | A01-A14 | Unit/API/integration/browser + gekennzeichnete Livechecks, Latenz/TTFC/Dauer/Fehler/RAM gemessen, keine Produktionsreife aus Unit allein |
| R19 | Arbeitsweise | M0-M5 | A14 | AGENTS/README/docs/STATUS, Requirementtrace, vertikale Meilensteine, keine Routinefreigaben, konkrete Blocker/Fortsetzung/Gitstatus |

## Abnahmefälle

| ID | Meilenstein | Beweisziel | Aktueller Nachweis |
|---|---|---|---|
| A01 | M1 | Einfache Frage: lokal, genau ein Router-/Antwortaufruf | Unit/API plus echte lokale Inlineantworten; Dataset 15/15, einfache Fälle mit genau einem Router-HTTP-Aufruf |
| A02 | M1 | Freigegebene komplexe Frage: OpenRouter im selben Chat | Echter OpenRouter-Modelltest und AUTO-End-to-End auf eigener VM; gemeldete Kosten, gleicher privater Kontext bleibt lokal |
| A03 | M0-M5 | LOCAL_ONLY aus Historie/Derivaten/Embedding/Web/n8n niemals extern | Privacy-Vertrags-/API-/HTTP-Gatewaytests und echte lokale Chat-Websuche mit synthetischer privater Historie bestanden; Embedding/n8n noch offen |
| A04 | M1 | Provider-/Mac-Ausfall: korrekter Status, kein verbotener Fallback | ConnectError-/Gatewaytests plus echte eigene Relay-Unterbrechung und Worker-Neustart mit automatischer Recovery; kein Cloudfallback |
| A05 | M2 | Dateien mit echten Fundstellen, projektisoliert, strukturierte Zahlenprüfung | bestanden auf eigener VM: neun Formate, lokale OCR, SHA-Originale, PDF-Fundstelle, Decimal-Summen, Scopeisolation und echter lokaler Quellenchat |
| A06 | M4 | DOCX/PPTX editierbar öffnen; rendern und Layout prüfen | teilweise: editierbare native Dateien, Linux-Vorschauen, mobile Dialoge, lokale Modellplanung, Word-Folgeversion, natürlicher Quellen-Chat, echte Chat-Folgeversionen, dichte Folien und vier Formate per HTTPS geprüft; breite Layout-/Faktenabnahme offen |
| A07 | M4 | PDF merge/split korrekt, Collage verwendet Originalbilder | teilweise: echte PDF-Auswahl/Rotation/Aufteilung in native Einzeldateien plus identisches ZIP und Bildzuschnitt/Collage mit Originalhash- und Pixelprüfungen sowie authentifizierter Live-Abnahme; Unicode-Collage v2 visuell/hashgeprüft; PNG-Alpha/Metadaten geprüft |
| A08 | M3 | Skillrevision wirkt und erweitert keine Rechte | implementiert und live geprüft: versionierte Regeln, Vertrauensprüfung, Auswahl und Audit; keine Rechteausweitung |
| A09 | M2 | Obsidian/App bidirektional: Konflikt/Löschung/Umbenennung/Restart | bestanden am vorhandenen Vault: kanonische Writes, externer Sync, Peer-Verfügbarkeit, Hash-Konfliktvergleich, Rename/Versionen/Archiv, Neustart-Reconcile; isolierte PG-Ausfalltests ohne produktive Mountunterbrechung |
| A10 | M3 | Chat erzeugt echten validierten n8n-Workflow; genehmigter Run im Task-Center | teilweise: normales Task-Center, lokale Entwürfe, echter n8n-Minutenworkflow, lokale Dokumentereignis-Aufgaben und genehmigte aufgabenbezogene n8n-Vorlage mit Callback/PG-Run live; achtknotiger begrenzter Abschlussgraph und geordnete lokale HA-/Analysefolge live, freie Graphgenerierung nicht unterstützt |
| A11 | M3 | Doppeltrigger/Retry: kein unkontrollierter doppelter Write | teilweise: eigene lokale Archive live in confirm_each und bounded_autonomous genau einmal ausgeführt, Replay sowie Pausenwiederherstellung geprüft; Termin-/Dokumentereignis-/n8n-Belege mit dauerhaftem Intent/Reconciliation; weitere externe Writes offen |
| A12 | M3 | HA-Wartung hält Freigabe/Backup/Fehlerstopp ein | teilweise: feste lesende HA-Prüfung live, Write-Sperre geprüft; Installation und Sicherungsmetadaten über feste WebSocket-Leseabfrage bestätigt; realer Wartungsbericht über PostgreSQL-Worker und lokaler HA-Chat gelesen; HA-Restore/Wartung offen |
| A13 | M1/M3/M5 | Persistente Titel/Historie, mobile Browser, Jobs ohne Client über Restart | Browser-/DB-Tests inklusive Edit/Retry und mobilen Layouts; PostgreSQL-Queue in CI; echte lokale Titel und Client-Disconnect/Cancel auf eigener VM geprüft |
| A14 | M0/M5 | Backup/Restore, private GitHub-Versionierung ohne Secrets/Runtime-Daten | Privates Repo/Source-/CI-gitleaks; verschlüsselte eigene VM-Sicherung, Off-VM-Kopie, Prüfsummen und isolierter Restore Schema 0024 mit 34 Dateiversionen samt Ausgaben/Vorschauen/PDF-Export, drei PDF-Teilen und zwei Recherche-/Querybelegen, mit Provider-/MCP-/Workflow-Masterkey, n8n-Bindung/Dispatch/Run, HA-Lesebelegen, Zeitplan-/Taskaudit, 55 Originalhashes, Memory und begrenzten SSH-Identitäten/Units bestanden; vollständige n8n-/HA-Sicherung und RTO/RPO bleiben offen |
