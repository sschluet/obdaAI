# obdaAI

Private self-hosted personal assistant: one AUTO chat with projects, knowledge,
tools, artifacts and n8n tasks. Development begins with an independent modular
monolith. The current implementation and outstanding work are in [STATUS](STATUS.md).
This repository contains no personal runtime data or deployment credentials.

## Local development
Python 3.12+, Node 24 LTS and uv 0.12.23. Run `uv sync --locked --all-extras`.
Create `.local/` first with `mkdir -p .local`. Generate a login hash using `uv run python scripts/create_login.py` and store it in your protected environment. Set environment variables from `.env.example` explicitly; the app never searches
for another project's secrets. Run `uv run alembic upgrade head` then
`uv run uvicorn hub.api:app --host 127.0.0.1 --port 8765`.
Build the UI with `cd frontend && pnpm install --frozen-lockfile --ignore-scripts && pnpm build`.
For local loopback development only, explicitly set `HUB_SECURE_COOKIE=false`;
production keeps secure cookies enabled. Production requires TLS, a unique login hash and encryption key, private approved
provider origins, separate PostgreSQL roles, backup verification and target approval.

## Checks
`uv run ruff check .`; `uv run mypy backend/hub`; `uv run pytest`;
`uv run python scripts/scan_secrets.py`; `cd frontend && pnpm check && pnpm build`.
Tests use only synthetic data. Browser/live and PostgreSQL tests must be reported
separately from local SQLite contract checks.

## Documentation
- [Requirements and acceptance](docs/requirements.md)
- [Architecture](docs/architecture.md), [security](docs/security.md), [data model](docs/data-model.md)
- [Implementation plan](docs/implementation-plan.md), [operations](docs/operations.md)
- [Provider configuration, encrypted secrets and budgets](docs/providers.md)
- [Versions and sources](docs/dependencies.md)
- [Operator n8n connection check](docs/n8n-connection-check.md)

## Current development limits
M1 implements login, durable AUTO chat with local/OpenRouter providers, streaming,
edit/retry/cancel, revision-preserving history, local asynchronous titles, German full-text
search, provider settings/tests, encrypted secrets, budgets and bounded execution.
PostgreSQL dispatch uses Procrastinate; start the separate process with
`uv run python -m hub.jobs`. Reopening a conversation follows stored events, and stalled
worker jobs reconcile partial output without repeating inference. See [STATUS](STATUS.md)
for exact CI and real-integration evidence and remaining acceptance limits.
M2 adds project sources/uploads, extraction/OCR, scoped knowledge chat, explicitly
approved public web research and canonical Vault Memory with revision comparison.
The authorized limited Vault/search integration is installed and live-tested on the
dedicated VM. M3 starts with fixed local actions, persisted proposals, explicit grants and receipts
([contract](docs/actions.md)); [trusted revisioned chat skills](docs/skills.md) are implemented; [manual local Task-Center](docs/tasks.md) is implemented. A fixed local analysis step applies bound sources and trusted skills. Local title drafts and [once/daily/weekly schedules](docs/schedules.md) are implemented. The production n8n clock bridge and external action adapters remain pending live acceptance.
M4–M5 are not implemented yet. Cloud remains disabled in generic defaults and needs an
explicit operator authorization plus conversation opt-in. Migrations must run before
startup. SQLite is for local contract tests/development; durable jobs use PostgreSQL.

A temporary synthetic browser fixture can be started with
`uv run uvicorn scripts.browser_fixture:app --host 127.0.0.1 --port 18765`;
then run `cd frontend && node browser-check.mjs`. It uses only synthetic data and
is never a deployment configuration. Build: `docker build -t obdaai .`; this builds
an image only. Production Compose, secrets, egress, TLS and VM provisioning remain
behind the deployment gates in docs/operations.md.
