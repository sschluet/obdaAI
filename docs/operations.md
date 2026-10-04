# Betrieb und Zielbereitstellung

## Aktueller Stand
Kein Hub auf einem produktiven Server installiert. Bestehende Dienste bleiben als
Rückfalloption. Interne Bestandsdaten stehen nur in `.local/inventory.md` (ignoriert).
Die Zielwahl (vorhandenes ai-core oder neue dedizierte VM) ist noch nicht
festgelegt; konkrete Installation/Provisionierung ist noch nicht freigegeben. Kein Proxmox-Token wird aus alten
Konfigurationen automatisch zum Provisionieren verwendet.

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
M5 liefert ausführbare Skripte und gemessene RTO/RPO; derzeit nicht nachgewiesen.

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
Compose und produktive Infrastruktur sind noch nicht installiert oder abgenommen.

Lokale Backends können nach Liveprüfung `HUB_LOCAL_DISABLE_THINKING=true` verwenden.
Dies ergänzt ausschließlich beim lokalen Adapter das nachgewiesen unterstützte
`enable_thinking:false`; standardmäßig wird kein vendorbezogenes Feld gesendet.
Der Router hat 1.024 Outputtokens und maximal einen Schema-Reparaturversuch.
