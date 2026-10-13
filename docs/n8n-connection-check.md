# Operator n8n connection check

This is a deliberately harmless first integration step, not A10 task execution.
The reviewed template contains only Manual Trigger -> No operation and no private
context, credentials or URLs. Installed node versions were checked read-only.

`hub.n8n_check.ConnectionCheck` and `scripts/n8n_connection_check.py` operate only
against the fixed approved HTTPS origin. TLS verification stays enabled, proxy
environment and redirects are disabled, and responses/timeouts are bounded. The
key is read from a private file, never a command argument or model context. The
adapter does not expose update, delete, activation, execution or credential APIs.

Before creation it finds the exact reviewed name and rejects ambiguity/drift.
Creation needs explicit human authorization for the specific reviewed payload.
The operator flag enforces a procedural gate; it is not an action grant and must
never be exposed to model-produced arguments or untrusted workflow content.

A mode-0600 journal records intent before POST, then the returned workflow ID/version and
verified receipt. A filesystem lock serializes operators using that journal. Use
exactly one protected journal for this binding on this workstation. The API does
not provide a verified create-idempotency contract: this is not an exactly-once
guarantee across machines or different journal paths.

An uncertain outcome is reconciled by exact name and whole graph. The adapter
never blindly repeats POST. Missing uncertain outcomes, duplicate names, active
workflows, data injection or drift require operator review; existing workflows
are not overwritten. Both the creation response and a subsequent GET must match
the inactive reviewed template. A successful check does not execute the task.

Validation on 05.10.2026: 24 tests cover creation/GET verification, duplicate and
concurrent operators, unapproved operation, unknown outcome and recovery, graph/
state/version drift, response limits, auth failures and redirects without secret output.
Real read-only lookup via the installed public API succeeded; creation stopped at
the approval gate, with no POST. Live creation was authorized by the user on 05.10.2026 and completed once.
The first strict comparison detected server-added settings. Read-only reconciliation
confirmed exactly callerPolicy=workflowsFromSameOwner and availableInMCP=false;
only these exact restricted additions are normalized, all others stop. The same
workflow was then verified without another POST, with matching ID/version/hash.
It remains inactive, without credentials or task execution.
No new VM egress rule or n8n setting is installed by this step.

API contract verified against the installed n8n 2.7.5 primary source:
[workflow GET/POST routes](https://raw.githubusercontent.com/n8n-io/n8n/n8n@2.7.5/packages/cli/src/public-api/v1/handlers/workflows/spec/paths/workflows.yml).

Next integration stages: approved inactive creation and read verification; a
reviewed gateway/execution binding; a harmless actual task run; drift detection,
restart and duplicate-trigger acceptance; then separately reviewed scheduling.
Task model/skill steps and HA/MCP/REST/browser adapters remain separate M3 work.
