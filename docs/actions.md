# M3 first vertical: fixed local actions

The authenticated Werkzeug page provides a fixed catalog, separate persisted proposals,
explicit time-limited grants, revocation, pause state and execution receipts. Local
adapters are `hub.inspect` (counts only) and `project.archive` (recoverable local
project archive at a specific revision). The optional `ha.inspect` adapter performs a fixed read-only Home Assistant assessment;
see `home-assistant.md`. There is no model tool loop or arbitrary external dispatcher. Private runtime audit stays in
the app database, never Git.

All proposals have strict tool schemas, a stable request key, canonical parameters
and SHA256, tool/policy revisions and server-assigned LOCAL_ONLY. Documents and
model text cannot register a tool, extend its schema or grant rights. Grants come
from the authenticated human endpoint after comparison and expire in 15–3600 seconds.
The UI uses five minutes. A pause transition invalidates outstanding write proposals
and grants. Revocation is persistent. An expired or changed grant requires a new
proposal; repeated execution of a completed action only returns the existing receipt.

Migration 0012 seeds the gateway paused. The policy singleton is locked during
approval/revocation/pause and execution. Project archival uses a conditional revision
update; its local database effect and unique receipt commit in one transaction.
Concurrent execution has one local effect. This is not an exactly-once claim for
external APIs: future external adapters need separately committed dispatch intents,
uncertain outcomes, reconciliation and target-specific idempotency before retries.

The global gateway pause governs these M3 writes. Direct authenticated M2 editor
operations remain explicit user actions with their existing revision safeguards.
Read tools can run while paused. Replaying receipts while paused never writes again.
Rollback to the M2 app preserves the additive schema. Schema downgrade refuses
nonempty action audit; export/preserve it rather than dropping history.

Contract tests cover unknown tools/URLs/parameters, label injection, authentication,
CSRF, stale request identity, incorrect digest, expiry, revocation, pause cycles,
target/version/privacy drift, concurrent duplicate execution, app restart and audit
preservation. A separate disposable PostgreSQL CI test exercises the actual row
lock and concurrent receipt contract. Browser checks use synthetic projects and
verify proposal → grant → execute, reload persistence and 390px width without overflow.
Live own-VM checks and external integrations are tracked separately in STATUS.md.
