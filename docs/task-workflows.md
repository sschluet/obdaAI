# Bound task workflows

A task created from an own chat message can prepare a revision-bound execution
workflow. The code-owned n8n 2.7.5 template uses Webhook 2.1 -> HTTP Request 4.4,
not free model code. Both paths use the same new per-binding header credential;
the callback uses the existing dedicated public-CA credential with certificate
validation and redirects disabled. The fixed callback origin is the reviewed
obdaAI installation. The webhook receives only a dispatch UUID; the callback
returns only dispatch/run/execution identities. Goal, source documents, skill
bodies, model prompts and answers remain in obdaAI.

Preparation saves only an encrypted local binding. Creation and publication are
separate proposed, time-limited, revocable ActionGateway grants bound to exact
binding/task/control/hash/version. Each external POST has a committed intent and
rechecks current pause, grant, expiry and task state at the final I/O boundary.
A supplied n8n Public-API key may have account-wide privileges; the optional
own-API-only readonly mount is a security-relevant installation step. It is never
mounted in workers/parsers or exposed to UI/model. Do not imply Community has
scopes it does not implement. Remote configuration and unrelated workflows are
never updated by this adapter.

New credential creation has no documented listing/recovery path: unknown outcome
stops without a second POST. Workflow creation reconciles a unique code-owned
name and exact graph/settings, with bounded listing. Unknown publication is only
confirmed by an exact active version, never blindly repeated. An irreversible
credential/workflow delete is not exposed. Existing credentials are neither
reused for unrelated authentication nor copied from existing workflows.

The Task-Center distinguishes draft, setup pending, verified, published and
uncertain. After explicit publication and task activation, a manual invocation
first validates the current remote graph/published version and commits its intent.
There is one pending invocation per binding. A lost webhook response does not
cause a second POST. The authenticated callback rechecks the remote graph,
task/source/skill revisions and control pause, then commits TaskRun, queue job
and execution linkage atomically. Repeated same execution returns its stored
identities; a different execution for the same dispatch is rejected. No private
content is returned to n8n. Workers continue after browser disconnect. Existing
clock-based task scheduling is retained; there is no second schedule in this
per-task workflow. Goal text never creates a free node, URL or credential.

An uncertain local dispatch can be revoked. This prevents a late callback from
being accepted; it is not a claim that a remote n8n execution was stopped. An
accepted task run uses the existing task cancellation path. Remote drift stops
the next invocation/callback and is never silently overwritten.

Validation and live installation evidence are recorded in STATUS.md. Local
transport/contract mocks are separate from actual n8n integration. Future arbitrary
multi-system workflow graphs remain subject to reviewed templates and adapters.

Primary sources checked against installed 2.7.5:
- [Webhook source/version](https://github.com/n8n-io/n8n/blob/n8n%402.7.5/packages/nodes-base/nodes/Webhook/Webhook.node.ts)
- [Webhook authentication and outputs](https://github.com/n8n-io/n8n/blob/n8n%402.7.5/packages/nodes-base/nodes/Webhook/description.ts)
- [Public API authentication](https://docs.n8n.io/api/authentication/)
