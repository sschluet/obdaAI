# Local task schedules

Migration 0015 keeps schedules separate from the existing immutable TaskSpec.
Existing tasks, sources, skills, results and manual triggers remain intact.
A schedule has immutable saved revisions and references the exact task revision,
control revision and spec hash. Editing a task requires reviewing its schedule again.

The ordinary task dialog offers manual, once, daily and weekly execution. A weekly
plan selects weekdays; all plans display a wall-clock time and IANA timezone.
Saving leaves the plan paused. Activation rechecks current source/skill bindings,
requires a recent n8n clock pulse and explicitly permits that local task to run.
Switching to manual saves a paused manual plan and retains earlier revisions.

n8n is the only clock engine. A fixed Schedule Trigger wakes once per minute and
POSTs an empty JSON object to `https://192.168.117.103/api/scheduler/tick`. The Hub
uses its own current time and stored plans; no supplied timestamps, task IDs,
URLs, model code, goals or document context are accepted by that endpoint. The
machine token grants no browser session, read API, gateway write or cloud access.
Only the technical count of newly queued runs is returned to n8n.

Task-lock serialization, a unique occurrence key and the existing one-active-run
constraint prevent duplicate/overlapping runs. Occurrence, task snapshot and
PostgreSQL queue insertion commit in one transaction. The existing local worker
revalidates task and context at execution. Pause/archive/edit invalidates an old
plan; binding drift blocks the occurrence and pauses the plan for review.

Clock pulses may arrive within 120 seconds of a due instant. Older overdue
occurrences are recorded as missed, with no automatic catch-up; recurrent plans
advance to their next future occurrence. An active prior run causes an explicit
skipped occurrence. There is no in-app cron or background task-scheduling loop.
A n8n outage does not affect manual runs. Plans cannot be newly activated without
a clock pulse in the last 180 seconds. Schedule edits and resumes select the next
future occurrence and never replay earlier results.

Spring DST gaps are skipped for recurring plans; repeated autumn wall times run
once at the first occurrence. Once-only ambiguous/nonexistent times are rejected.
Historical occurrences retain their planned UTC instant and link to durable runs,
results and errors. Schedule changes have separate immutable revision snapshots.

## Deployment and live acceptance

Default runtime is disabled. `HUB_SCHEDULER_ENABLED=false` requires no new secret.
The optional reviewed `deploy/scheduler.compose.yaml.in` mounts only a dedicated
256-bit clock token into the own API containers. The fixed workflow constructor
in `backend/hub/n8n_schedule.py` binds two credential identities: `httpHeaderAuth`
for the limited token and `httpSslAuth` containing only the public obdaAI CA.
The HTTP Request follows no redirects and keeps certificate verification enabled.
It uses n8n 2.7.5 Schedule Trigger 1.3 and HTTP Request 4.4, verified against the
installed node inventory and official versioned source:
[Schedule Trigger](https://github.com/n8n-io/n8n/blob/n8n%402.7.5/packages/nodes-base/nodes/Schedule/ScheduleTrigger.node.ts),
[HTTP Request](https://github.com/n8n-io/n8n/blob/n8n%402.7.5/packages/nodes-base/nodes/HttpRequest/V3/HttpRequestV3.node.ts),
[SSL credential](https://github.com/n8n-io/n8n/blob/n8n%402.7.5/packages/nodes-base/credentials/HttpSslAuth.credentials.ts).

The user explicitly approved exactly two new n8n credentials and one own clock
workflow, including synthetic local read acceptance. Future credential or existing
service changes still follow AGENTS.md's access boundary. Prepare an inactive workflow,
compare exact nodes/settings/credentials before activation, record identity/version
and reconcile any unknown API outcome before retrying a write. Credentials APIs
have no verified public list/read endpoint in this installed version: an uncertain
credential-creation result must be reconciled by an operator, not blindly repeated.
Never change existing workflows, n8n container settings or TLS policy.

The installed bridge uses a dedicated workflow and retains its credential IDs,
workflow ID/version and write-ahead reconciliation journal only in the protected
operator directory. It does not modify existing n8n workflows. The clock's only
runtime static data is Schedule Trigger recurrence timestamps; node definitions,
credential references, destination and access settings stay exactly bound.

All own future Compose updates must include `-f scheduler.compose.yaml` alongside
`compose.yaml`, `https.compose.yaml` and `vault.compose.yaml`; otherwise Compose
would remove the clock token mount. Ordinary container restarts retain it. The
own encrypted backup includes both the private token and the optional overlay.
Recovery restores the same token; an existing n8n credential must not be silently
replaced or duplicated. Protect the workstation journal for external identity
reconciliation. An uncertain credential POST never gets an automatic second POST.

Live evidence belongs in STATUS.md and protected operator receipts. Tests must
separately establish real n8n wake-up, once/daily/weekly local read results, next
calendar dates, pause at a due minute, results after restart and isolated encrypted
restore. Synthetic unit/browser checks alone do not establish the live bridge.
