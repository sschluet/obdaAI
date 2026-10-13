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

Remaining M3: chat-generated arbitrary validated n8n workflows, external
reconciliation/execution, OAuth/stdio MCP and isolated browser adapters, plus
separately accepted Home Assistant maintenance. Real minute-clock scheduling and
local task execution are installed; see schedules.md and STATUS.md.

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
limits, context bounds and provider revision drift reject the preview. Scheduling uses the human date/time form and the installed n8n minute clock.
MCP connection drafts and bounded catalog checks are described in mcp-connections.md.

## From a chat message to a task

An explicit “Als Aufgabe planen” button on an own message opens the normal task
editor with that exact message as its goal and the optional project. No assistant
answer, hidden history, source selection, skill, cloud permission or schedule is
automatically inherited. Messages above the 4000-character task limit cannot be
transferred and are never silently truncated. No model or API is called until the
user saves normally. The title can be edited; the new task is stored paused and
requires the existing separate activation. Cancelling the dialog saves nothing.
The transfer draft is consumed once, so reopening Tasks does not duplicate it.


## Ordered local evidence and bounded listing queries

An explicitly reviewed hub-status → local-analysis task passes the exact persisted
read receipt into the final local model prompt, labelled LOCAL_ONLY and audited as
`task-step:<run>:<sequence>`. Source/skill limits and final provider revision checks
still apply. The real two-stage local model run and natural-language ordered draft
passed on the own VM, with no cloud call; the test task was archived afterward.

Task listing fetches tasks, current immutable revisions, schedules, write grants and
latest run metadata in five bulk reads. Ranking uses created time and ID as a stable
tiebreaker. Full run snapshots/steps are not loaded by that list. The same strict spec
hash/revision validation and schedule/grant serializers remain in the detail path.
A 26-task regression checks constant query count, identical summaries, archived
entries, latest-run ties, paused/drifted plans, consumed grants and corrupted hashes.
The change responds to a measured 120-request HTTPS sample (concurrency four), where
the previous per-task queries caused task-list p95 around 1.64 seconds. After deployment, the same bounded 120-request sample measured task-list p95
540.29 ms (previously 1642.24 ms), and overall p95 469.97 ms. This sample does not
include inference, task writes or full-load certification.


## Document-ready events

The ordinary editor supports the bounded source_ready trigger for one explicit
project and local read/analysis steps. Schema 0022 preserves a cursor and unique
first-readiness events without sending content to the existing n8n clock. Runs
retain unchanged source selection and final worker authorization checks. See
[source-ready-tasks.md](source-ready-tasks.md) for baseline, pause, overlap and
120-second missed-event behavior. Other event types remain unsupported.
