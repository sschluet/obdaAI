# Dedizierter obdaAI-Pilot

Diese Dateien gelten ausschließlich für eine neue, zuvor geprüfte Debian-13-VM mit
Hostname `obdaai`. Sie sind kein Installer für die bestehende LocalAI-Plattform.
Der Pilot enthält den M1-Teilstand, keine vollständige V1.

Vor der Provisionierung: freie VM-ID, Kapazität, Netzpfad, offizielle Image-Prüfsumme,
SSH-Hostkey und konkrete Zielautorisierung prüfen. Zugangsdaten und Bestandsbelege
bleiben außerhalb von Git. Cloud ist deaktiviert; es gibt keinen Cloudfallback.

## Ablauf auf der neuen VM

1. `bootstrap-debian.sh` einmal als root ausführen. Das Skript prüft Host/OS und
   verweigert die Wiederholung. Die Docker-Adresspools müssen zuvor gegen alle
   Host-/Client-/VPN-Routen geprüft werden; die eingebauten Pools sind ein Pilotbeispiel.
   Paketversionen werden unter `/etc/obdaai/packages.lock` dokumentiert.
2. Den geprüften Gitstand nach `/opt/obdaai/releases/<commit>` kopieren. Die Compose-
   Build-Context auf dieses Verzeichnis setzen. Release in `/etc/obdaai/release.env`
   als `HUB_RELEASE=<commit>` festlegen. Keine private Runtime in den Build kopieren.
3. Eigene zufällige Datenbank- und Loginpasswörter erzeugen. Nur den scrypt-Loginhash
   in `/etc/obdaai/runtime.env` speichern. Datenbanksecret gehört dem DB-Containeruser,
   lokaler Inference-Key UID 10001; jeweils nur für diese User lesbar. Elternordner 0700.
4. `egress.sh` auf der neuen VM installieren und durch eine eigene systemd-Oneshot-Unit
   vor Docker beim Boot anwenden. Die Unit muss beim Fehler Dockerstart verhindern.
   API/Worker dürfen UID 10001 und Host-Networking nicht verlieren: darauf beruht die Sperre.
5. Konfiguration prüfen, Image bauen, Datenbank starten, Migration durchführen:

```sh
cd /opt/obdaai
docker compose --env-file /etc/obdaai/release.env config --quiet
docker compose --env-file /etc/obdaai/release.env build api
docker compose --env-file /etc/obdaai/release.env up -d db
docker compose --env-file /etc/obdaai/release.env run --rm -T migrate </dev/null
docker compose --env-file /etc/obdaai/release.env up -d api worker
```

## Runtime und Zugriff

`HUB_DATABASE_URL` zeigt auf die eigene Datenbank an 127.0.0.1:5432.
`HUB_LOCAL_BASE_URL=http://127.0.0.1:11443/v1`, `HUB_LOCAL_ALLOWED_IP=127.0.0.1`,
`HUB_LOCAL_KEY_FILE=/run/secrets/local-inference.key`, `HUB_CLOUD_ENABLED=false`.
Modell-ID ist am echten Backend zu prüfen. API hört nur an 127.0.0.1:8765.
Der Pilot leitet diese Adresse durch SSH auf den Arbeits-Mac weiter; `HUB_ORIGIN`
muss exakt mit dessen Browseradresse übereinstimmen. `HUB_SECURE_COOKIE=false`
ist nur für den verschlüsselten SSH-Pilot mit Browser-Loopback vorgesehen.
Für einen permanenten Browserzugang privates HTTPS und Secure-Cookies einrichten.

Die aktuelle Modellverbindung verwendet ebenfalls einen beaufsichtigten SSH-Relay
auf dem Arbeits-Mac. Ohne diesen Relay schlägt lokaler Chat fehl; er wechselt niemals
zur Cloud. Keine bestehende Tailnet-ACL oder Inference-/SSH-Konfiguration wurde dafür
geändert. Neue serverseitige Berechtigungen separat und zielgebunden freigeben.

## Prüfung, Sicherung und Rückkehr

Health, Anmeldung, echtes lokales Modell, persistierte Nachrichten, Queue-Schema,
Containerrechte und ausgehende Sperre auf der VM prüfen. Bestehende Proxmox-VMs,
Storage-, Netzwerk- und Firewallkonfiguration mit dem vorherigen Beleg vergleichen.
Service-Restarts ersetzen keine vollständige Host-Reboot-Abnahme.

Für Backups einen PostgreSQL-Custom-Dump erstellen und vor der Ablage authentifiziert
verschlüsseln. Schlüssel getrennt vom Server sicher aufbewahren. Restore zuerst in
**einer separaten Testdatenbank** prüfen; niemals automatisch die aktive DB überschreiben.
Der Pilot hat keinen automatischen Backupplan. Eine erfolgreiche Einzelprobe ersetzt
keine periodische Wiederherstellungsprüfung.

Rollback: ausschließlich den eigenen Compose-Stack stoppen (kein `down -v`),
Datenvolume und Backups bewahren. Ein Approllback muss zum vorhandenen DB-Schema passen.
VM-/Volume-Löschung, Restore über bestehende Daten und Entzug vorhandener Deployzugänge
sind eigene Entscheidungen. Keine bestehenden Plattformdienste abschalten.
