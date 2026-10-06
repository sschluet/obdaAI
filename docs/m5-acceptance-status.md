# M5-Abnahme: Betrieb, Performance und verbleibende Nachweise

Stand 06.10.2026. Eigene VM: Anwendung `c13e41f`, Schema 0022. M5 ist teilweise
abgenommen; synthetische Transporttests sind keine echten Anbieter-/Geräteabnahmen.

| Bereich | Tatsächlicher Nachweis | Noch offen |
|---|---|---|
| Deployment | Eigene App und netzloser Dateirunner gebaut, Backup/Rückweg vor Installation, API-Gesundheit und unveränderte IPv4-/IPv6-Regeln geprüft | Keine allgemeine Hochverfügbarkeitszusage |
| CI | Sechs Jobs für denselben Anwendungscode auf dem finalen PR-Stand: Python mit PG, Secrets, Frontend mit drei Browserchecks, Appcontainer, Browserrunner, Dateirunner | Abschließenden CI-Status direkt im PR prüfen |
| Lokale Prüfung | 471 Tests, ruff/mypy und Source-Scan bestanden; elf PG-Fälle separat auf echter temporärer DB bestanden | Breiter Belastungs-/Fehlerkorpus |
| Oberfläche | Normale Projekt-/Datei-/Task-/Providerdialoge, mobile Chromium-Fixtures, Initialbundle etwa 446 kB durch Lazy Panels | Reale Safari-/Mobilgeräteabnahme |
| Performance | 120 authentifizierte GETs, vier Clients, keine Inference/Mutation: Aufgaben p95 1642 → 540 ms, Gesamt-p95 470 ms; fünf gebündelte Task-DB-Reads | Vollast, Konkurrenz zwischen Inference/Uploads/Rendering, Dauer-/RAM-Messung unter Last |
| HTTPS / Auth | Gepinntes eigenes Zertifikat, unauthentifiziert 401, Secure/HttpOnly/SameSite, fehlende CSRF/fremde Origin 403, Logout invalidiert Sitzung; Projektzahl unverändert | Keine externe Penetrationstest-/Sicherheitszertifizierungsbehauptung |
| Nach Rollout | 40 Health-GETs mit vier Clients: p95 52.0 ms; globale Schreibpause aktiv | Health-Latenz ist keine Chatlatenz |
| Restore | Verschlüsselte eigene DB/Konfiguration off-VM, Prüfsummen, temporärer Schema-0022-Restore; 23 Dateiversionen mit Ausgabe-/Vorschau-/PDF-Hashes, 46 Originale, 6 Memory-Dateien, Masterkey/Workflow-/begrenzte SSH-Schlüssel sowie Dokumentereignisse, Cursor und gebundene Laufdigests geprüft; temporäre DB entfernt | Vollständige HA-/n8n-Archive, Wiederherstellung und gemessene RTO/RPO |
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
