# M5-Abnahme: Betrieb, Performance und verbleibende Nachweise

Stand 06.10.2026. Eigene VM: Anwendung `80179bc`, Schema 0024. M5 ist teilweise
abgenommen; synthetische Transporttests sind keine echten Anbieter-/Geräteabnahmen.

| Bereich | Tatsächlicher Nachweis | Noch offen |
|---|---|---|
| Deployment | Eigene App und netzloser Dateirunner gebaut, Backup/Rückweg vor Installation, API-Gesundheit und unveränderte IPv4-/IPv6-Regeln geprüft | Keine allgemeine Hochverfügbarkeitszusage |
| CI | Sechs Jobs für denselben Anwendungscode auf dem finalen PR-Stand: Python mit PG, Secrets, Frontend mit fünf Browserchecks, Appcontainer, Browserrunner, Dateirunner | Abschließenden CI-Status direkt im PR prüfen |
| Lokale Prüfung | 577 Tests einschließlich PostgreSQL in aktueller CI bestanden; Ruff/mypy (61 Module)/Source-Scan und fünf lokale Browserchecks bestanden | Breiter Belastungs-/Fehlerkorpus |
| Oberfläche | Normale Projekt-/Datei-/Task-/Providerdialoge, mobile Chromium-Fixtures, Initialbundle etwa 446 kB durch Lazy Panels | Reale Safari-/Mobilgeräteabnahme |
| Performance | 120 authentifizierte GETs, vier Clients, keine Inference/Mutation: Aufgaben p95 1642 → 540 ms, Gesamt-p95 470 ms; fünf gebündelte Task-DB-Reads | Maximale Kapazität, längere Lastdauer und Mac-mini-RAM/TTFC verschiedener Modellklassen |
| HTTPS / Auth | Gepinntes eigenes Zertifikat, unauthentifiziert 401, Secure/HttpOnly/SameSite, fehlende CSRF/fremde Origin 403, Logout invalidiert Sitzung; Projektzahl unverändert | Keine externe Penetrationstest-/Sicherheitszertifizierungsbehauptung |
| Nach Rollout | 40 Health-GETs mit vier Clients nach vorherigem Rollout plus abschließende Auth-/CSRF-Prüfung; reale Mischlast unten dokumentiert; globale Schreibpause aktiv | Health-Latenz ist keine Chatlatenz |
| Restore | Verschlüsselte eigene DB/Konfiguration off-VM, Prüfsummen, temporärer Schema-0024-Restore; 34 Dateiversionen mit Ausgabe-/Vorschau-/PDF-/Teildateihashes, zwei Recherche-/Querybelege und 55 Originale, 6 Memory-Dateien, Masterkey/Workflow-/begrenzte SSH-Schlüssel sowie Dokumentereignisse, Cursor und gebundene Laufdigests geprüft; temporäre DB entfernt | Vollständige HA-/n8n-Archive, Wiederherstellung und gemessene RTO/RPO |
| Anbieter | OpenRouter real geprüft; direkte OpenAI Responses/Anthropic Messages mit verschlüsselter Konfiguration, Quellen-/Anbieter-Consent, Budgetreservierung, SSE- und Kostenschätzungsgrenzen implementiert | Eigene native Schlüssel und konkrete Ausgangsfreigabe fehlen; keine realen nativen Requests |

Dateiläufe erhalten Originalrevisionen/Hashes, fixe Befehle und private begrenzte
Dateikopien; keine Modellskripte/Makros/freien URLs. Externe Anbieter werden vor DNS
gegen LOCAL_ONLY und konkrete Zustimmung geprüft. Logs enthalten bei unerwarteten
Chatfehlern nur die Fehlerklasse, keine Prompts, SQL-Parameter oder Schlüssel.
Eingebettete Bildmetadaten werden bereinigt; transparente Pixel bleiben erhalten.

Vier eigene synthetische QA-Projekte und acht Testchats sind wiederherstellbar
archiviert, Originale erhalten; andere Projekte wurden dabei nicht geändert. Kein produktiver
HA-Write/Restore. Vorhandene HA-Backupmetadaten belegen weder Archivintegrität noch
den verfügbaren Wiederherstellungsschlüssel. Kein fertiger V1-/M5-Merge aus diesen
Teilnachweisen. Weitere Funktionslücken: docs/m3-acceptance-status.md und
docs/m4-acceptance-status.md; native Transportgrenzen: docs/native-provider-status.md.


## Begrenzte reale Mischlast auf bf03aa3

120 authentifizierte Lesezugriffe gleichzeitig mit zwei TXT-Uploads mit je
2200 Zeilen, zwei nativen Word-Läufen und zwei lokalen Chatläufen. Alle
Hintergrundaufträge abgeschlossen, Originalhashes unverändert, keine Cloudaufrufe.
GETs: p50 69,38 ms, p95 232,87 ms, Maximum 1290,15 ms; null HTTP-Fehler.
Erste sichtbare Chatdaten inklusive Client-/Queuewartezeit: 18,22 und 10,227 s.
160 Container-RAM-/CPU-Samples; Peak RAM API 145,1 MiB, HTTPS-API 98,03 MiB,
Chatworker 83,37 MiB, Quellenworker 83,14 MiB, Artefaktworker 83,34 MiB,
Dateirunner 217,5 MiB, Parser 9,86 MiB und DB 172,5 MiB.

Vorherige Textdarstellung scheiterte bei 2200 Einzelzeilen an 2000 Einheiten.
Die korrigierte begrenzte Fenstereinteilung erhält jede Zeile/Fundstelle und
wurde mit derselben Last tatsächlich geprüft. Der erste Fehlbeleg bleibt erhalten.
Eigene QA-Räume/-Chats sind archiviert, andere Aufgaben und globale Schreibpause
blieben erhalten. Dies ist ein begrenzter Single-User-Mischlastfall; kein
Sättigungs-, Dauertest, Mac-mini-RAM- oder allgemeiner RTO/RPO-Nachweis.
