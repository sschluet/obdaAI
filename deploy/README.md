# Dedizierter obdaAI-Pilot

Diese Dateien gelten ausschließlich für eine neue, zuvor geprüfte Debian-13-VM mit
Hostname `obdaai`. Sie sind kein Installer für die bestehende LocalAI-Plattform.
Der Pilot enthält die M1-Implementierung; M2–M5 sind noch keine vollständige V1.

Vor der Provisionierung: freie VM-ID, Kapazität, Netzpfad, offizielle Image-Prüfsumme,
SSH-Hostkey und konkrete Zielautorisierung prüfen. Zugangsdaten und Bestandsbelege
bleiben außerhalb von Git. Cloud ist im Ausgangszustand deaktiviert; es gibt keinen Cloudfallback.

## Ablauf auf der neuen VM

1. `bootstrap-debian.sh` einmal als root ausführen. Das Skript prüft Host/OS und
   verweigert die Wiederholung. Die Docker-Adresspools müssen zuvor gegen alle
   Host-/Client-/VPN-Routen geprüft werden; die eingebauten Pools sind ein Pilotbeispiel.
   Paketversionen werden unter `/etc/obdaai/packages.lock` dokumentiert. Der private
   Provider-Masterkey wird einmalig erzeugt, gehört UID 10001 und liegt außerhalb der DB.
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
`HUB_LOCAL_BASE_URL=http://127.0.0.1:11444/v1`, `HUB_LOCAL_ALLOWED_IP=127.0.0.1`,
`HUB_LOCAL_KEY_FILE=/run/secrets/local-inference.key`, `HUB_CLOUD_ENABLED=false`,
`HUB_SECRETS_KEY_FILE=/run/secrets/provider-encryption.key`.
Modell-ID ist am echten Backend zu prüfen. API hört nur an 127.0.0.1:8765.
Der Pilot leitet diese Adresse durch SSH auf den Arbeits-Mac weiter; `HUB_ORIGIN`
muss exakt mit dessen Browseradresse übereinstimmen. `HUB_SECURE_COOKIE=false`
ist nur für den verschlüsselten SSH-Pilot mit Browser-Loopback vorgesehen.
Für einen permanenten Browserzugang privates HTTPS und Secure-Cookies einrichten.

Die Modellverbindung läuft als eigener systemd-Dienst auf der VM. Dafür gibt es
`model-relay.service` und eine rootgeschützte `/etc/obdaai/relay.env` mit `RELAY_HOST`.
Der private Schlüssel bleibt ausschließlich auf der VM. Den bereits verifizierten
Mac-mini-Hostkey in die separate Known-Hosts-Datei kopieren; kein ungeprüftes TOFU.
Ohne das lokale Backend schlägt Chat fehl; er wechselt niemals zur Cloud.

Auf dem Mac mini wurde ausdrücklich ein neuer Benutzer `hub-relay` freigegeben.
`model-relay.sshd.conf` ist eine Vorlage für einen Block **am Ende** der sshd_config,
kein globales Include-Fragment. Vorher Backup und effektive Regeln für bestehende
Benutzer vergleichen, danach `sshd -t` und `sshd -T -C ...` prüfen. Kein gemeinsamer
SSH-Service-Restart war nötig. Root verwaltet dessen separate AuthorizedKeys-Datei:
Schlüssel mit `from="<VM-IP>",restrict,port-forwarding,permitopen="127.0.0.1:11435",command="/usr/bin/false"`.
Nur Public-Key-Authentifizierung und lokales TCP-Forwarding zum Modellport sind erlaubt.
MaxSessions 0 sperrt Shell/Befehle/SFTP; Remote-, Unix-Socket-, Agent-, X11- und
Tunnel-Forwarding sind gesperrt. Der Benutzer ist kein Administrator und hat kein
nutzbares Passwort. macOS-PAM benötigt eine akzeptierte Kontoshell; `/bin/sh` wurde
für genau diesen Benutzer separat vom Nutzer erlaubt, SSH-Sessions bleiben gesperrt.
Bestehende Inference-Einstellungen und Tailnet-ACLs bleiben erhalten.

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

## Privates HTTPS

Der zusätzliche HTTPS-Endpunkt bewahrt den bisherigen SSH-Pilot während der
Zertifikatsabnahme. Beide APIs verwenden dieselbe Datenbank und denselben Worker.
`https.compose.yaml` erweitert die geprüfte Basis, lauscht nur an 127.0.0.1:8766
und liest `/etc/obdaai/https.env` zuletzt: exakte HTTPS-Origin und
`HUB_SECURE_COOKIE=true`. Die API bleibt ohne öffentliche Bindung.

Auf der neuen VM das geprüfte Debian-Nginx-Paket installieren und die genaue Version
im privaten Paketbeleg sichern. Den automatischen Start der Standardseite während
Installation verhindern; vorhandene Paketstartregeln niemals überschreiben.
Den unangetasteten Standard-Sitelink bewahren und deaktivieren. Die Vorlage
`nginx-https.conf.template` mit der geprüften privaten IPv4-Adresse rendern.
Kein Port 80, kein öffentliches ACME, keine Host-/Origin-Umschreibung.
SSE benötigt ausgeschaltetes Proxy-Buffering; keine automatische Wiederholung von
POSTs auf einem zweiten Upstream. Vor Start `nginx -t` prüfen.

`https-network.sh` prüft ausschließlich RFC1918-Netze und liest rootgeschützte
`/etc/obdaai/https-network.env`: `HUB_HTTPS_BIND_IP` und durch Leerzeichen getrennte
`HUB_HTTPS_CLIENT_CIDRS`. Erst die konkret autorisierten privaten Clientnetze eintragen.
Die eigene INPUT-Chain begrenzt HTTPS; die Proxy-UID darf ausgehend nur zur lokalen
HTTPS-API verbinden. `https-network.service` und `nginx-network.conf` sorgen für
Anwendung vor Nginx; bei Fehler verhindert Requires den Start. API-/Worker-Egress
enthält den zusätzlichen Healthcheck-Port 8766. Keine anderen Hostchains leeren.

```sh
docker compose --env-file /etc/obdaai/release.env \
  -f /opt/obdaai/compose.yaml -f /opt/obdaai/https.compose.yaml \
  --profile https config --quiet
docker compose --env-file /etc/obdaai/release.env \
  -f /opt/obdaai/compose.yaml -f /opt/obdaai/https.compose.yaml \
  --profile https up -d --no-build api_https </dev/null
```

Der Pilot verwendet ein selbstsigniertes einzelnes Serverzertifikat (CA:FALSE,
ServerAuth, SAN für geprüfte private Adresse), dessen privater EC-Schlüssel allein
root auf der VM lesen kann. Das konkrete öffentliche Zertifikat und SHA256-
Fingerabdruck getrennt bereitstellen. TLS-Tests vertrauen ausschließlich diesem
Zertifikat; weder `verify=false` noch eine deaktivierte Namensprüfung verwenden.
Browser-/Schlüsselbund-Vertrauen erfordert eine separate Nutzerentscheidung.
Keine Warnung automatisch übergehen, keine allgemeine CA installieren. Ein manuell
freigegebener macOS-Import kann SSL-Vertrauen auf genau diesen Servernamen beschränken.

Abnahme: echtes lokales Gespräch über direkte TLS-Verbindung, Secure/HttpOnly/
SameSite-Cookie, falsche Origin/fehlender CSRF abgewiesen, falscher Zertifikatsname
abgewiesen, Proxy-Egress gesperrt und vollständiger Reboot der neuen VM.
Der alte Browser-Tunnel bleibt bis zur sichtbaren Browserabnahme erhalten.
Rollback: ausschließlich Nginx und api_https stoppen; gemeinsame DB/Worker bewahren.

Die geprüfte IP muss stabil bleiben; derzeit DHCP mit festem VM-MAC. Eine DHCP-
Reservierung erfordert gesonderte Routerfreigabe. Bei Adresswechsel sind Bindung,
Clientregeln, Origin, SSH-Quellbeschränkung und Zertifikat anzupassen. Zertifikat
läuft nach einem Jahr ab; Erneuerung und Clientvertrauen sind noch nicht automatisiert.

## Automatische verschlüsselte Sicherung

`backup.sh`, `backup.service` und `backup.timer` gelten ausschließlich für die eigene
VM. Offizielles Debian-age-Paket mit dokumentierter Version installieren. Einen
**separaten** age-/SSH-Ed25519-Wiederherstellungsschlüssel auf dem Arbeitsplatz erzeugen;
private Identity niemals auf den Server kopieren oder für SSH-Anmeldung freigeben.
Nur den öffentlichen Empfänger in rootgeschützte `/etc/obdaai/backup-recipients`
schreiben. Keine bestehenden Deploy-Schlüssel als Backup-Identity verwenden.

Der Timer läuft täglich ab 03:00 Europe/Berlin mit bis zu zehn Minuten Zufallsverzug
und holt ausgefallene Termine nach. Er sichert den PostgreSQL-Custom-Dump sowie
Runtime/TLS/Relay-/SSH-/Compose-/Netzwerk-Konfiguration als zwei age-Dateien.
Die Daten werden durch Pipes verschlüsselt; kein Klartext-Dump auf dem Dateisystem.
Snapshots werden erst nach beiden erfolgreichen Pipelines und SHA256-Beleg atomar
veröffentlicht. Sperrdatei verhindert überlappende Läufe; fehlgeschlagene eigene
Staging-Verzeichnisse werden verworfen. Bereits veröffentlichte Sicherungen bleiben
erhalten. Ein 10-GiB-Backupbudget und mindestens 1 GiB verbleibender freier Speicher
begrenzen den Betrieb; bei Überschreitung scheitert der Dienst mit Journalmeldung.

Die Unit hat ausschließlich lokale Unix-Sockets und schreibt nur ins Backup- und
Lockverzeichnis. Home-Verzeichnisse sind nur lesbar, damit die freigegebenen
SSH-Public-Keys mitgesichert werden. Der Wiederherstellungsschlüssel bleibt außerhalb
der VM. Erst manuell starten, erfolgreichen Lauf prüfen, dann Timer aktivieren.

Für Restore die verschlüsselten Dateien und SHA256-Belege zuerst auf einen anderen
Rechner kopieren. Dort mit der privaten Identity entschlüsseln und den Custom-Dump
zunächst in eine **getrennte** Datenbank zurückspielen. Konfigurationsarchiv zuerst
prüfen; kein unkontrolliertes Entpacken über `/`. Ein Restore aktiver Daten oder
Wiederaufnahme gesicherter Queue-Jobs ist eine eigene Entscheidung, kein Timerjob.
Offizielle age-Dokumentation: https://github.com/FiloSottile/age .

Ein verschlüsselter Snapshot wurde auf dem Arbeitsplatz gesichert und ein echter
isolierter Datenbank-Restore sowie die Entschlüsselung der Betriebskonfiguration
geprüft. Weitere automatische Off-VM-Kopien, Alarmierung und eine Aufbewahrungs-/
Löschpolicy sind noch offen. Der Wiederherstellungsschlüssel braucht eine separat
aufbewahrte sichere Kopie; die VM-Sicherung allein ersetzt diese nicht.

## Optionale OpenRouter-Freigabe

Die ausdrückliche Betreiberfreigabe gilt für die eigene VM, synthetische Abnahme und
ein definiertes Testbudget. Nur dann `HUB_CLOUD_ENABLED=true` setzen und den Marker
`/etc/obdaai/openrouter-egress.enabled` anlegen. `egress.sh` übernimmt aktuelle öffentliche
IPv4-Ziele für den offiziellen Host und DNS zum vorhandenen Stubresolver; IPv6 und
übrige App-Ziele bleiben gesperrt. Marker vor Deaktivierung entfernen und Filter neu laden.
Provider-Schlüssel über die authentifizierte API/UI verschlüsselt speichern; Modell aus
dem echten Katalog wählen, Verbindung testen und ein kleines positives Budget festlegen.
Private Gespräche bleiben unabhängig davon lokal. Details: [Providerbetrieb](../docs/providers.md).

## M2-Datenverarbeitung

Vor Start die eigenen Verzeichnisse `/var/lib/obdaai/sources` und
`/var/lib/obdaai/parser-results` mit Eigentümer 10001:10001, Modus 0700 erzeugen.
Runtime: `HUB_SOURCE_DIR=/sources`, `HUB_PARSER_RESULT_DIR=/parser-results`.
Compose startet zusätzlich `source-worker` und den strikt netzwerklosen `parser`.
Der Parser benötigt Linux Landlock ABI >=3; fehlende Unterstützung ist ein Fehler,
kein Anlass, Dateisystem- oder Netzwerkisolation zu deaktivieren.
Backup umfasst die eigenen Originale und Ergebnisse zusammen mit DB/Config.

Vorhandenen Vault und Webdienst erst lesend inventarisieren. Für dauerhafte Verbindungen
eigene, begrenzte Zugänge verwenden; keine älteren Admin-/Hermes-Credentials übernehmen.
`HUB_VAULT_DIR` / `HUB_VAULT_WRITABLE`, `HUB_SEARCH_URL` / `HUB_SEARCH_ALLOWED_IP`
und `HUB_WEB_DOMAINS_JSON` erst nach konkreter Zugangsfreigabe konfigurieren.
Bestehenden Vault-Sync nicht ersetzen oder einen konkurrierenden Sync installieren.
