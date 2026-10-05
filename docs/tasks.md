# Manual local read tasks

Migration 0014 adds Task, immutable TaskRevision, TaskRun and TaskStep. This first
Task-Center vertical supports create/edit, pause/resume, manual run, queued cancel,
and recoverable archive/restore. Every new or edited specification starts paused.
The UI exposes specification hashes, old revisions, last run, steps and manifests.

The strict TaskSpec allows only manual `analyze_only`, `LOCAL_ONLY`, zero USD and
one to five fixed `hub.inspect` reads. It validates the IANA timezone; scheduling
and UTC/DST execution are not implemented. Goal text never becomes executable
code. Unknown fields, tools, credentials, network targets and autonomy upgrades
are rejected. Bound project sources and trusted skills require current revision,
hash and scope. Their bindings are checked again at the worker boundary. Skills
are audited in this read manifest; they are not applied to a model in this vertical.

A task control revision prevents pause/resume or edit races. Starting requires
both revisions and the reviewed spec hash. The request UUID binds to the complete
canonical request; repeated requests return the same run, altered reuse fails.
An independent PostgreSQL advisory lock and a partial unique index prevent
concurrent active runs. Procrastinate enqueue and TaskRun commit use the same
transaction. The actual worker persists the read results and final receipt in one
transaction. Duplicate delivery sees that receipt. Stalled queue recovery uses
worker heartbeat, without introducing a second scheduler. SQLite dispatch is a
local development fixture and is not a production durability claim.

Read-only steps have no external side effect. This does not establish retry or
exactly-once guarantees for future remote writes. Cancelling a queued run wins
before execution; already completed reads cannot be cancelled. Task writes never
change the global action gateway pause policy.

The export endpoint compiles a separate n8n connection-check draft containing
only Manual Trigger -> No operation. It carries technical UUID/revision/hash
binding, no goal, source contents, skill documents, credentials or URLs. Exact
whole-graph validation rejects extra nodes, parameters, edges and settings.
Installed n8n 2.7.5 node inventory confirmed both nodes at typeVersion 1 on
05.10.2026. Export does not upload, activate or execute a workflow, and does not
execute the task. Creating it on the existing n8n needs separate operator approval.

Validation: 14 task API/lifecycle/drift/concurrency tests and seven compiler tests;
real PostgreSQL atomic enqueue and duplicate-worker receipt test in CI. Synthetic
browser: paused creation, resume, read receipt, reload, revision 2 with preserved
revision 1/receipt, archive/restore paused; 390px without horizontal overflow.
Production integration evidence is recorded separately in STATUS.md.

Remaining M3: natural-language TaskSpec generation, model task steps, actual n8n
execution binding and scheduling/DST, external reconciliation, task skill effects,
MCP/REST/browser adapters and separately approved Home Assistant maintenance.
