# Home Assistant: read-only maintenance inventory

`ha.inspect` is a fixed authenticated read tool, separate from model/task execution.
It reads only `/api/config` and `/api/states` at the reviewed Home Assistant origin.
No prompts, project data, documents, user-selected URLs or parameters are transmitted.
The API token stays in a private regular secret file mounted only in the own API and
API-HTTPS services. It may possess broader HA privileges; this adapter exposes no
write operation and does not claim that the upstream token itself is read-only.

The runtime requires both `HUB_HA_TOKEN_FILE` and an explicitly reviewed public IPv4
`HUB_HA_ALLOWED_IP`. Requests connect directly to that IP, with the fixed Host and TLS
SNI name; certificate verification remains enabled. No redirects, environment proxies
or arbitrary paths. Changes to the target address require operator review. The two
responses have an 8 MB limit each, eight-second transport timeout and an eighteen-second
read deadline checked during iteration. Unknown or malformed schemas fail closed.

The persisted LOCAL_ONLY receipt retains version, reported installation type if any,
Supervisor/backup integration presence and only update-entity names/states/versions.
Other entity data, coordinates, release summaries/URLs and response bodies are discarded.
Remote names are displayed as plain text, never HTML or tool instructions. Results
are not inserted into model context. Refresh creates a new explicitly requested
assessment; replay of a completed action returns its saved receipt without another
HA request. Failed reads save no success receipt. No automatic read retries occur.
The existing gateway transaction lock serializes executions, including this bounded
read; this is an interactive tool, not a scheduled task adapter.

The UI explains available/unknown updates and preserves the result after reload.
Supervisor or backup integration presence proves neither exact installation type nor
successful backup/restore. `restore_verified` and `writes_enabled` remain false. No
update, restart, backup creation or restore service is callable. Production HA
maintenance remains a separate unfinished M3 acceptance case.

For authorized own-VM activation render `deploy/home-assistant.compose.yaml.in` with
the reviewed address, preserve the current egress script and add only the specific
outbound IPv4 TCP/443 allowance. Keep all existing Compose overlays, especially the
scheduler overlay. Include the optional HA overlay in subsequent rollouts and backups.
Rollback restores the original own release/egress script and removes only the new
HA overlay/allowance; it makes no changes to HA or existing n8n workflows.

Sources checked 05.10.2026:
- [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/)
- [Update entity semantics](https://www.home-assistant.io/integrations/update/)
- [Backup and restore prerequisites](https://www.home-assistant.io/integrations/backup/)

## Own-VM activation verified 05.10.2026

After explicit token-mount/outbound-IP approval, source `75c7f04` was installed with
the HA and existing scheduler overlays, schema 0015. The supplied HA credential is
mounted read-only only in API/API-HTTPS; workers/parsers have no HA credential mount.
Exactly one approved HA TCP/443 rule was inserted before the own chain's existing
REJECT. All prior rules were compared and preserved. The persistent own egress script
contains the corresponding marker-controlled rule, with the previous release/script
and database saved for rollback. No HA or n8n configuration was changed.

The own egress unit uses RemainAfterExit: starting an already active unit does not
reapply its script. Activation therefore verified and inserted only the new rule
without flushing the existing chain. Subsequent authorized egress reloads must account
for that unit behavior and compare retained rules.

Authenticated, certificate-verified live app acceptance: fixed HA GET assessment
succeeded (2026.9.3, 55 update entries, two available), durable receipt replay matched,
other actions/tasks remained unchanged. The clock stayed healthy and all four prior
scheduled results/history were retained. Write actions remain paused; HA maintenance
backup/restore readiness remains unverified.

Encrypted off-VM backup and isolated schema-0015 restore passed: the HA read receipt
matched exactly, credential/overlay/approved egress marker were present, and prior
schedules, 40 original source hashes and six Memory files survived. The disposable
restore database was removed. This proves hub recovery only, not HA backup or restore.

## Installation und vorhandene Sicherungen

`ha.backups.inspect` nutzt ausschließlich die offizielle Core-WebSocket-API
`/api/websocket`. Genau drei fest codierte Kommandos: supervisor/api GET /info,
supervisor/api GET /supervisor/info und backup/info. Keine freien Methoden/Pfade,
keine Backup-Erzeugung, Downloads, Konfigurationsabfragen mit Schlüsseln oder Restore.
Das vorhandene HA-Tokenfile und die geprüfte IP werden verwendet: direkte TCP-
Verbindung zu genau dieser IP, Host/TLS-SNI aus dem festen WSS-URI, Zertifikat
geprüft, Proxy/Kompression ausgeschaltet, keine Redirect-/Reconnect-Schleife.
Transportlogger deaktiviert, damit kein Auth-Frame geloggt wird.

Reproduzierbar gepinntes websockets 17.1 (BSD) begrenzt Nachrichten auf 1 MB und
zwei gepufferte Frames. Maximal acht Sekunden je Receive und 24 Sekunden für
den Austausch; Verbindung/Close separat auf acht/zwei Sekunden begrenzt. Unerwartete
Authentifizierung, ID, Event, Erfolgsflag oder Schema stoppt ohne Folgeaktion.

Die Ausgabe enthält Installation/Core/Supervisor, Gesundheits-/Supportflags,
Sicherungsdienstzustand, Zeit der zuletzt laut HA abgeschlossenen automatischen
Sicherung und minimierte Backup-Metadaten. Keine Backup-Namen, Agentkennungen,
Addon-/Ordnernamen, Error-Texte, private Extradaten oder Wiederherstellungsschlüssel.
Metadaten und Fremdaussagen sind keine Integritäts-/Restore-Abnahme. Die drei Flags
archive_integrity_verified, recovery_key_verified und restore_verified bleiben false,
Schreibaktionen bleiben gesperrt. Belegreplay ruft die Quelle nicht erneut auf.

Die zuvor untersuchten HTTP-Supervisor-Pfade liefern in Core 2026.9.3 401, weil
sie im HTTP-Proxy nicht freigegeben sind; daraus darf kein fehlendes Adminrecht
des Tokens abgeleitet werden. Die dokumentierten WebSocket-Lesewege wurden
erfolgreich geprüft: HA OS 18.3, gesunder/unterstützter Supervisor 2026.09.3,
61 gemeldete Sicherungen, kein gemeldeter Agentfehler. Produktives HA unverändert.

Primärquellen:
- https://raw.githubusercontent.com/home-assistant/core/2026.9.3/homeassistant/components/hassio/http.py
- https://raw.githubusercontent.com/home-assistant/core/2026.9.3/homeassistant/components/hassio/websocket_api.py
- https://raw.githubusercontent.com/home-assistant/core/2026.9.3/homeassistant/components/backup/websocket.py
- https://websockets.readthedocs.io/en/stable/reference/sync/client.html
