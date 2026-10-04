# Personal AI Hub

Private self-hosted personal assistant: one AUTO chat with projects, knowledge,
tools, artifacts and n8n tasks. Development begins with an independent modular
monolith. The current implementation and outstanding work are in [STATUS](STATUS.md).
This repository contains no personal runtime data or deployment credentials.

## Local development
Python 3.12+, Node 24 LTS and uv 0.12.23. Run `uv sync --locked --all-extras`.
Set environment variables from `.env.example` explicitly; the app never searches
for another project's secrets. Run `uv run alembic upgrade head` then
`uv run uvicorn hub.api:app --host 127.0.0.1 --port 8765`.
Build the UI with `cd frontend && npm ci && npm run build`.
Production requires TLS, a unique login hash and encryption key, private approved
provider origins, separate PostgreSQL roles, backup verification and target approval.

## Checks
`uv run ruff check .`; `uv run mypy backend/hub`; `uv run pytest`;
`uv run python scripts/scan_secrets.py`; `cd frontend && npm run check && npm run build`.
Tests use only synthetic data. Browser/live and PostgreSQL tests must be reported
separately from local SQLite contract checks.

## Documentation
- [Requirements and acceptance](docs/requirements.md)
- [Architecture](docs/architecture.md), [security](docs/security.md), [data model](docs/data-model.md)
- [Implementation plan](docs/implementation-plan.md), [operations](docs/operations.md)
- [Versions and sources](docs/dependencies.md)
