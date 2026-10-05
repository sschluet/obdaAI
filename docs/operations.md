# Betrieb und Zielbereitstellung

## Aktueller Stand
Die eigene dedizierte obdaAI-VM ist mit PostgreSQL, API/Workern, Offline-Parser,
HTTPS-Proxy und restriktiven Netzwerkregeln installiert. M1 wurde mit echten lokalen
und OpenRouter-Smokes geprüft. M2 nutzt ausdrücklich freigegebene begrenzte Vault-
und Suchzugänge; allgemeiner Vault readonly, ausschließlich AI/Memory writable.
Bestehender Sync und Inference bleiben erhalten. Aktuelle Releases, CI und echte
Abnahmen stehen in STATUS.md; interne Inventardaten und Belege bleiben unter
`.local/`. Neue Zugänge/Änderungen an bestehenden n8n-/HA-Systemen erfordern eine
konkrete Freigabe; die App erbt keine Rechte älterer Assistenzsysteme.

## Deployment-Gates
1. Zielwahl bestätigen; bei neuer VM deren ID/Adresse und Host-Kapazität prüfen; konkrete Provisionierung
   freigeben. Debian 13, Startannahme 4 vCPU/8 GiB/80 GiB.
2. Unterstützte Docker Engine/Compose-Version und Images/Digests prüfen und pinnen.
3. Neue App-DB/Rolle anlegen, Migration prüfen, Schlüssel außerhalb DB sichern.
4. Erlaubte private Ziele, DNS/SSRF-Schutz und restriktiven Egress installieren.
5. TLS-Proxy/Firewall auf ausgewähltem Ziel; keine öffentliche DB/n8n/Inference.
6. Bestehendes n8n: Backup/Workflow-/Credential-Inventar und öffentliche API prüfen;
   kontrollierte Migration statt doppelter Terminierung. Alter Dienst bleibt Rückweg.
7. Vault zunächst nur read-only; begrenzter Memory-Pfad nach Freigabe beschreibbar.
8. Live-Smokes und negative Privacy-Tests, Browser/mobile, Dauerjobs ohne Client.
9. Konsistentes Backup/Restore in Testumgebung beweisen, dann Abnahme.

## Sicherung / Wiederherstellung
App-DB, Uploads/Ergebnisse, Vault-Memory, n8n-DB und Credentials, externe Schlüssel
und Konfiguration gemeinsam sichern. Backups verschlüsseln; Schlüssel separat.
Restore ohne produktives Netz: DB migrieren, Files/Hashes prüfen, Memory reconcile,
Jobs mit unklarem Ausgang markieren, Writes/global autonomy pausieren. n8n-Zeitpläne
nicht automatisch nachholen. VM-Snapshot/GitHub ersetzen diese Sicherung nicht.
`deploy/backup.sh` erstellt verschlüsselte eigene VM-Sicherungen; die separate
Wiederherstellungsidentität bleibt auf dem WorkMac. M2-Restore auf Schema 0011 prüft
Originalhashes, Provider-Masterkey, begrenzte SSH-Identitäten/Units und Memory-Dateien.
Fehlender Mount und Transportfehler wurden an einer isolierten restaurierten
PostgreSQL-Kopie geprüft, ohne den produktiven Mount zu unterbrechen. n8n-/HA-Daten
sind noch keine Bestandteile dieser eigenen VM-Sicherung. Gemessene RTO/RPO und
vollständige systemübergreifende Wiederherstellung bleiben M5-Abnahme.

## Messung
Request-ID ohne Inhalt; Routerlatenz, TTFC, Dauer, Fehlerstatus, bekannte usage,
Queuewait und Runner-RAM messen. Logs ohne Prompts/Secrets, Rotation und Retention.
Mac-mini-Anfragen serialisieren und Chat gegenüber Batch priorisieren. Timeouts
und Retries begrenzen. Kein Exactly-once-Versprechen; Writes vor Retry abgleichen.

## M1 Entwicklungsimage
Dockerfile baut die statische UI und die Python-App mit Lockfiles. Das Runtime-Image
läuft als UID/GID 10001, enthält weder Runtime-Daten noch Secrets und führt keine
Migration beim Start aus. Provider-Keyfiles müssen für diese UID ausschließlich
lesbar sein (0600/0400); vorhandene gruppengeschützte Altplattform-Keys werden nicht
automatisch umberechtigt. Der aktuelle Adapter unterstützt nur explizit erlaubte
lokale IPs und den festen offiziellen OpenRouter-Origin; weitere Provider-UI folgt.
Die eigene Compose-Bereitstellung ist installiert; Abnahmen und verbliebene Grenzen
stehen in STATUS.md. Vorhandene fremde Dienste sind keine impliziten Deploymentziele.

Lokale Backends können nach Liveprüfung `HUB_LOCAL_DISABLE_THINKING=true` verwenden.
Dies ergänzt ausschließlich beim lokalen Adapter das nachgewiesen unterstützte
`enable_thinking:false`; standardmäßig wird kein vendorbezogenes Feld gesendet.
Der Router hat 1.024 Outputtokens und maximal einen Schema-Reparaturversuch.

## M1 Queue und Wiederaufnahme
`uv run alembic upgrade head` legt unter PostgreSQL zusätzlich das dedizierte Schema
`hub_queue` aus Procrastinate 3.10.0 an. Ausschließlich eine neue, eigene Hub-DB verwenden.
Die Migration läuft in derselben Transaktion und installiert keinen Zeitplan.
API und Worker verwenden dieselbe `HUB_DATABASE_URL` und Provider-Konfiguration:

```sh
uv run uvicorn hub.api:app --host 127.0.0.1 --port 8765
uv run python -m hub.jobs
```

Beide Befehle benötigen jeweils einen eigenen Prozess. Worker-Concurrency ist 1.
Ein Run und sein Queue-Job werden atomar auf derselben psycopg-Verbindung committed.
Der Browser beobachtet persistierte SSE-Ereignisse; Schließen/Reload beendet den Run
nicht. Das Öffnen eines laufenden Gesprächs verbindet die UI erneut. API-Neustarts
ändern PostgreSQL-Runstatus nicht. SQLite bleibt ausschließlich Entwicklung: separater
Async-Task, keine dauerhafte Queue, API-Neustart markiert offene Runs unterbrochen.

Abbruch vor Workerstart setzt den Run sofort auf cancelled; danach überwacht die
Ausführung alle 200 ms die Abbruchanforderung, auch während Provider-I/O. Provider-Timeouterror spätestens
nach 30 Sekunden bzw. Gesamtlimit 90 Sekunden. Kein automatischer Provider-Retry,
kein Cloudfallback. Worker-Shutdown lässt bis zu 95 Sekunden zum Abschluss.
Bei hartem Workerabbruch den gestoppten Prozess zuerst nachweisen und den stalled Job
mit den Procrastinate-Verwaltungsfunktionen gezielt erneut dispatchen. Die Taskfunktion
rekonstruiert gespeicherte Delta-Ereignisse als LOCAL_ONLY-Teilantwort und markiert den
Run interrupted, ohne den Provider erneut aufzurufen. Automatische stalled-Reconciliation,
UI-Administration und Retention für Queue/Ereignisse sind noch offen.

Quelle für atomare Übergabe: [Procrastinate external connections](https://procrastinate.readthedocs.io/en/stable/howto/production/external_connection.html).
Schema und Updates: [offizielle Migrationsanleitung](https://procrastinate.readthedocs.io/en/stable/howto/production/migrations.html).

## M1 Providerbetrieb

[Providerkonfiguration und Limits](providers.md) beschreibt Endpunktfreigaben, AES-GCM-Keys,
Revisionen und Budgetreservierungen. Der Masterkey wird in Compose read-only aus
`/etc/obdaai/secrets/provider-encryption.key` eingebunden. Das Backup archiviert bereits
`/etc/obdaai` vollständig; der isolierte Restore muss zusätzlich die Entschlüsselbarkeit
der Providersecrets nachweisen. Metriken unter `/api/metrics` sind authentifiziert.
OpenRouter nur nach eigener Ziel-/Budgetfreigabe aktivieren, Testdaten synthetisch halten
und bei fehlenden frischen Preisen den Verbindungstest wiederholen. Der Operator-Marker
für `deploy/egress.sh` ist keine Berechtigung des Assistenten für beliebige Netzwerkziele.
