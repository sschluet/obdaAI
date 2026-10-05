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
