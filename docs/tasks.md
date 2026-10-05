# Manual local read tasks

Migration 0014 adds Task, immutable TaskRevision, TaskRun and TaskStep. This first
Task-Center vertical supports create/edit, pause/resume, manual run, queued cancel,
and recoverable archive/restore. Every new or edited specification starts paused.
The UI exposes specification hashes, old revisions, last run, steps and manifests.

The strict TaskSpec allows only manual `analyze_only`, `LOCAL_ONLY`, zero USD,
fixed `hub.inspect` reads and at most one final `ai.analyze` local text step. It validates the IANA timezone; scheduling is stored separately in migration 0015; see [schedules](schedules.md)
for clock integration and UTC/DST behavior. Goal text never becomes executable
code. Unknown fields, tools, credentials, network targets and autonomy upgrades
are rejected. Bound project sources and trusted skills require current revision,
hash and scope. Their bindings are checked again at the worker boundary. For ai.analyze, the
trusted skill bodies and only the explicitly bound source chunks enter the local
model prompt. Pure hub.inspect reads audit bindings without inference.

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

Validation: 17 task API/lifecycle/drift/concurrency/corrupt-manifest tests and seven compiler tests;
real PostgreSQL atomic enqueue and duplicate-worker receipt test in CI. Synthetic
browser: paused creation, resume, read receipt, reload, revision 2 with preserved
revision 1/receipt, archive/restore paused; 390px without horizontal overflow.
Production integration evidence is recorded separately in STATUS.md.

Remaining M3: natural-language TaskSpec generation, actual n8n
execution binding and scheduling/DST, external reconciliation,
MCP/REST/browser adapters and separately approved Home Assistant maintenance.

## Fixed local model step

ai.analyze uses only the configured local provider. The local-only runtime path
neither loads cloud secrets nor enables cloud egress. It bypasses classification
for this explicit text-analysis step, never executes model-produced tools/code,
and applies context/output/time bounds. Provider revision/model, complete labelled
prompt, roles, partial/final text and zero cloud cost are recorded in TaskStep.
The TaskRun input snapshot remains immutable. No hidden chat history or unbound
project sources are appended.

A running claim commits before inference. A separate PostgreSQL session advisory
lock prevents simultaneous duplicate inference and keeps task pause/cancel locks
independent. On actual recovery of a running claim, partial text remains and the
run stops without a second inference call. Cancellation requests keep the active
run guard until acknowledgement; timeout/error also preserve existing partial
text. Task/control/source/skill/provider drift is rechecked while streaming and
before final completion. The session lock is released before returning its DB
connection to the pool. SQLite's process lock is a development-only fixture.

Twelve synthetic model/API tests cover context, skill effects, source isolation,
partial failure, cancel, recovery, duplicates, strict schemas and unloaded cloud
secrets. A real PostgreSQL session-lock independence/release test runs in CI.
Browser fixture confirms completed analysis, recorded context and 390px width.
Real model acceptance and deployment are recorded separately in STATUS.md.

## Human task editor and local title preview

The UI accepts a title, goal, fixed task kind, optional project and explicit
ready-source/trusted-skill checkboxes. It constructs the strict specification;
users need no JSON input. Natural-language preview uses only the local model
to propose a title. Goal and all permissions remain code-owned: manual, local
analysis, no sources, no skills, no execution, zero cloud cost. The authenticated
CSRF-protected endpoint saves nothing. Invalid JSON, extra model fields, output
limits, context bounds and provider revision drift reject the preview. Scheduling
and MCP registration remain open; the interface does not advertise them as active.
