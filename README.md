# obdaAI

Private self-hosted personal assistant: one AUTO chat with projects, knowledge,
tools, artifacts and n8n tasks. Development begins with an independent modular
monolith. The current implementation and outstanding work are in [STATUS](STATUS.md).
This repository contains no personal runtime data or deployment credentials.
Public project presentation: [obdaAI website](https://sschluet.github.io/obdaAI/).

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
- [Public project website and update workflow](docs/project-website.md)
- [Integrated workspace and local UX delivery](docs/ux-optimization.md)
- [Provider configuration, encrypted secrets and budgets](docs/providers.md)
- [Web research settings and connection check](docs/web-settings.md)
- [Versions and sources](docs/dependencies.md)
- [Gmail-Postfach und OAuth-Einrichtung](docs/gmail-mailbox.md)
- [Paperless-Dokumente und Integrationsfreigaben](docs/paperless.md)
- [KI Use Cases: Prompt, Eingabedateien, Dialog und Ausgabe](docs/ai-use-cases.md)
- [Operator n8n connection check](docs/n8n-connection-check.md)

## Current development limits
M1 implements login, durable AUTO chat with local/OpenRouter providers, streaming,
edit/retry/cancel, revision-preserving history, local asynchronous titles, German full-text
search, provider settings/tests, encrypted secrets, budgets and bounded execution.
PostgreSQL dispatch uses Procrastinate; start the separate process with
`uv run python -m hub.jobs`. Reopening a conversation follows stored events, and stalled
worker jobs reconcile partial output without repeating inference. See [STATUS](STATUS.md)
for exact CI and real-integration evidence and remaining acceptance limits.
M2 adds project sources/uploads, extraction/OCR, scoped knowledge chat, public web
research with a persistent user-controlled switch and canonical Vault Memory with
revision comparison.
The authorized limited Vault/search integration is installed and live-tested on the
dedicated VM. M3 starts with fixed local actions, persisted proposals, explicit grants and receipts
([contract](docs/actions.md)); [trusted revisioned chat skills](docs/skills.md) are implemented; [manual local Task-Center](docs/tasks.md) is implemented. A fixed local analysis step applies bound sources and trusted skills. Local title drafts and [once/daily/weekly schedules](docs/schedules.md) are implemented. The approved n8n clock bridge is installed; external action adapters remain in development.
M4 delivers tested local file workflows and revisions; M5 has deployment, CI, mobile
fixture and isolated restore evidence. Both remain partially accepted. Cloud remains disabled in generic defaults and needs an
explicit operator authorization. In the authorized ordinary Auto chat, the browser
provides the standing current-input cloud permission; private sources and old
LOCAL_ONLY history retain their boundary. Routing is configurable and explained
under Settings → Routing. Migrations must run before
startup. SQLite is for local contract tests/development; durable jobs use PostgreSQL.

A temporary synthetic browser fixture can be started with
`uv run uvicorn scripts.browser_fixture:app --host 127.0.0.1 --port 18765`;
then run `cd frontend && node browser-check.mjs`. It uses only synthetic data and
is never a deployment configuration. Build: `docker build -t obdaai .`; this builds
an image only. Production Compose, secrets, egress, TLS and VM provisioning remain
behind the deployment gates in docs/operations.md.


Personalization is available under Settings → About me: optional personal facts,
explicit field sharing and an immutable per-run profile snapshot. The revised
[skill library](docs/skills.md) supports Markdown instruction files, reviewed
activation, always/keyword/explicit-invocation modes and a chat picker. Private
profile fields and skill revisions need their own explicit cloud sharing. See
[personal profile](docs/personal-profile.md) and STATUS for acceptance evidence.

### Intelligent memory — verified limited delivery

The memory extension reuses the existing application database, personal profile,
revisioned Vault notes and provider boundary. New app-native memories also work
without an Obsidian mount; existing Vault notes remain canonical Markdown and keep
their original write/sync rules. Changing the chat model or provider does not move
or delete memories.

Under **Knowledge → Personal memory**, you can inspect, correct and forget memories,
review suggestions and choose an enabled local model for learning. Background
learning admits conservative direct user assertions, not ordinary questions,
pasted documents or mailbox contents. A small closed parser handles complete direct
statements about a daughter or son's name, age and riding ability before model
extraction. Riding duration accepts digits and German number words from one to
twelve; unsupported or ambiguous wording is not guessed. Other admitted assertions
use the configured local model, without increasing its confidence after the fact.
Sensitive suggestions retain source pointers
until explicit review. Facts, plans, hypotheses and decisions remain distinct;
conflicting facts require review or an explicit correction. The existing
**Settings → About me** profile remains independently editable and is never silently
overwritten by learned facts. Manually selected response preferences also retain
their authority over learned style preferences.

Memories are private by default. Cloud use requires an explicit grant for the
particular provider and current memory revision; ordinary Auto permission does
not share private memories. Auto keeps relevant private memory local; explicit
Cloud omits unshared memory rather than silently sending it. Retrieval combines
structured/lexical selection with
optional local embeddings stored in the same database. Local extractive summaries
help preserve older conversation context within a bounded window. Both remain
limited selections, not a complete record of everything ever discussed.

Migration **0046** adds metadata and derived-state tables without rewriting existing
notes, profiles or conversations. Forgetting removes app-memory text, its memory
versions and derived vectors, but does **not** erase original conversations,
historical run snapshots or external backups. The architecture and current
acceptance gaps are recorded in [Architecture](docs/architecture.md) and
[STATUS](STATUS.md). Release **aa4a5ae / schema 0046** passed 2707 local tests and
[exact full CI](https://github.com/sschluet/obdaAI/actions/runs/39647243916) (2701 passed, 6 skipped). Its app-only patch
preserved schema 0046 and existing native memories. A new synthetic real HTTP-chat
and PostgreSQL-worker acceptance passed profession recall and explicit correction:
these exact statements use a narrow deterministic parser; a real local answer
model responds. This does not prove LLM extraction of the correction. The first
2c85335 attempt learned/recalled the initial fact but failed the correction and
remains recorded separately. Optional real embeddings and general language or
long-term learning quality remain unverified. See STATUS for precise evidence,
original-history retention and backup/rollback limits.

Endgültiges Entfernen von Projekten und Gesprächen ist in [docs/deletion.md](docs/deletion.md) beschrieben; die Oberfläche zeigt vorab Umfang und erhaltene unabhängige Inhalte.
Die Modellwahl bietet **Auto**, **Nur lokal** und **Cloud** ohne zusätzlichen Anbieter-Dialog; Unterschiede und Freigabegrenzen stehen in [docs/model-modes.md](docs/model-modes.md).
Projekte erhalten unter **Projekt bearbeiten** ein konfigurierbares Logo aus 32 frei verwendbaren Lucide-Symbolen; Suche, Vorschau, lokale Darstellung und Lizenzhinweise siehe [docs/project-icons.md](docs/project-icons.md).

Verbindungen und kontrollierte Aktionen findest du unter **Einstellungen → Integrationen**. Direkte Prüfergebnisse, geführte Archivierung und Ausführungsbelege sind in [docs/integrations.md](docs/integrations.md) beschrieben.

Generische Verbindungsprofile mit Tabelle, Aktivschalter und Projekt-/Aufgaben-/Chatzuordnungen sowie lokale Formular-Use-Cases mit optionalem Projektbezug und direkten Auswahlfeldern im eigenen Navigationsbereich zwischen Projekte und Aufgaben: [Ausbauvertrag und Grenzen](docs/generic-integrations-and-use-cases.md). Der neue [Agentenweg](docs/agent-system-control.md) verwendet diese Profile auch für mehrstufige Systemsteuerung aus Chat, Aufgaben und Projekten, nach separat eingerichteten Agentenregeln. [Offizielle Anschlusswege weiterer Dienste](docs/integration-services-research.md) unterscheiden API, OAuth, Bridge und Dateiimport.

Oberfläche mit eigenem App-Namen, Anzeigenamen, Foto, Abständen und Akzentfarbe: [Persönliche Oberfläche](docs/appearance-customization.md). Anzeigeangaben sind vom persönlichen KI-Profil getrennt.

OpenRouter-Kontostatus und Nutzungskosten: [Einrichtung und Bedeutung der Werte](docs/openrouter-cost-status.md). Kontoguthaben benötigt einen separaten Management Key; Modellschlüssel und lokale Budgetgrenzen bleiben getrennt.

HTTPS hinter einer vom Benutzer eingerichteten Synology: [Reverse-Proxy-Vertrag und VM-Vorbereitung](docs/synology-reverse-proxy.md). Der private IP-Zugang bleibt erhalten; der Domainzugang akzeptiert nur den freigegebenen Proxy.

CI startet schwere App-Prüfungen nur für einen noch nicht vollständig geprüften App-Baum; Website und Dokumentation werden gezielt geprüft: [CI-Umfang, Nachweise und Push-Bündelung](docs/ci-efficiency.md).

Längere Konzepte, klare Teilantworten und manuelle Fortsetzung: [Antwort-, Kontext- und Kostenlimits](docs/answer-limits.md).

- [Use Cases: Integrationsphasen, KI-Erstellungsdialog und Mailversand](docs/use-case-integrations.md)

Kontrollierte Integrationsänderungen mit eigener Profilfreigabe, lokaler KI-Vorbereitung, Vorschau, Ausführungsbeleg und lesendem Fehlerabgleich: [Schreibadapter und Grenzen](docs/integration-writes.md). Noch keine vollständige administrative Fremdsystemabnahme.
