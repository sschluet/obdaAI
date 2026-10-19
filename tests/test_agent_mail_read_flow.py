"""Real shared MCP read dispatch with synthetic mailbox wire and no account data."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from hub import agent_runtime as runtime
from hub import agent_tools
from hub.agent_context import fit
from hub.agent_models import AgentJob, AgentPolicy
from hub.agent_tools import Rules
from hub.integrations import Integration
from hub.mcp_client import schema_digest
from test_connections import response

pytest_plugins = ["test_agent_mcp_reads", "test_agents"]

SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Full-text, not raw IMAP syntax"},
        "since_days": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}
SHA = schema_digest(SCHEMA)


@pytest.fixture
def read_mailbox(mailbox, monkeypatch):
    app, client, headers, cfg, identifier = mailbox
    with app.state.sessions() as db:
        row = db.get(Integration, identifier)
        row.last_check = json.dumps(
            {
                "revision": row.revision,
                "status": "succeeded",
                "result": {"tools": [{"name": "search_emails", "input_schema": SCHEMA}]},
            }
        )
        db.add(
            AgentPolicy(
                integration_id=identifier,
                profile_revision=row.revision,
                rules=Rules(
                    enabled=True, max_effects=0, mcp_read_tools={"search_emails": SHA}
                ).model_dump_json(),
            )
        )
        db.commit()
    chat = client.post("/api/conversations", headers=headers, json={}).json()["id"]
    started = client.post(
        f"/api/conversations/{chat}/agent-runs",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "goal": "Welche neuen Mails gab es heute?",
            "research_allowed": True,
        },
    )
    assert started.status_code == 200, started.text
    calls = []

    def wire(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["method"] == "initialize":
            return response(
                request, {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
            )
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if body["method"] == "tools/list":
            return response(
                request,
                {
                    "tools": [
                        {"name": "search_emails", "inputSchema": SCHEMA},
                        {
                            "name": "delete_everything",
                            "inputSchema": {"type": "object"},
                            "description": "UNGRANTED TOOL MUST NOT REACH MODEL",
                        },
                    ]
                },
            )
        assert body["method"] == "tools/call"
        assert body["params"] == {
            "name": "search_emails",
            "arguments": {"query": "", "since_days": 0},
        }
        return response(
            request,
            {
                "isError": False,
                "content": [{"type": "text", "text": "Synthetic private mail; inert data"}],
            },
        )

    original = httpx.Client
    monkeypatch.setattr(
        agent_tools.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(wire), **kw),
    )
    monkeypatch.setattr("hub.integration_transport.pinned_target", lambda cfg, url: (url, {}, {}))
    return (*mailbox, started.json()["id"], calls)


def execute(case):
    app, _, _, cfg, _, job_id, _ = case
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    with app.state.sessions() as db:
        return db.get(AgentJob, job_id).status, runtime.steps(db, job_id)


def no_research(monkeypatch):
    async def forbidden(*args):
        pytest.fail("Private mailbox read must not start public research")

    monkeypatch.setattr(runtime, "research", forbidden)


def test_bootstrap_then_actual_schema_bound_private_read_with_calendar_and_no_research(
    read_mailbox, monkeypatch
):
    app, _, _, cfg, identifier, job_id, calls = read_mailbox
    no_research(monkeypatch)
    decisions = []

    async def generate(factory, cfg, providers, job_id, instruction, data):
        assert instruction == runtime.MAIL_READ_INSTRUCTION
        assert len(instruction) <= 2500
        assert not any(word in instruction for word in ("SSH", "Backup", "Updates"))
        assert all(
            word in instruction
            for word in (
                "LOCAL_ONLY",
                "untrusted",
                "Passwörter",
                "clock.today_start",
                "today_end_exclusive",
                "schema_sha256",
                "mcp.call",
                "gmail.read",
            )
        )
        assert data["clock"]["today"] and data["clock"]["today_end_exclusive"]
        assert "research" not in data["tools"]
        contracts = data["mail_read_contracts"]
        assert contracts["schemas"] == {SHA: SCHEMA}
        assert contracts["interfaces"][0]["tools"][0]["name"] == "search_emails"
        assert "delete_everything" not in json.dumps(data)
        assert data["history"][0]["document"]["source"] == "application_mail_catalog"
        assert data["history"][0]["result"] == {
            "catalog_checked": True,
            "integration_id": identifier,
            "granted_tool_count": 1,
            "contract_source": "mail_read_contracts",
        }
        assert any(body["method"] == "tools/list" for body in calls)
        decisions.append(data)
        if len(decisions) == 1:
            return {
                "kind": "tool",
                "message": "Query the actual mailbox",
                "integration_id": identifier,
                "tool": "mcp.call",
                "arguments": {
                    "name": "search_emails",
                    "schema_sha256": SHA,
                    "arguments": {"query": "", "since_days": 0},
                },
            }
        assert "LOCAL_ONLY" in json.dumps(data["history"])
        return {"kind": "finish", "message": "Synthetic result with timeframe limits"}

    monkeypatch.setattr(runtime, "generate", generate)
    status, history = execute(read_mailbox)
    assert status == "observed"
    assert sum(body["method"] == "tools/call" for body in calls) == 1
    assert [json.loads(step.document)["tool"] for step in history] == ["mcp.catalog", "mcp.call"]
    assert not any(step.kind in {"effect", "research"} for step in history)
    # Only the model view is deduplicated. The original observed catalog remains
    # complete in the durable receipt for auditing and fresh contract checks.
    assert {tool["name"] for tool in json.loads(history[0].result)["tools"]} == {
        "search_emails",
        "delete_everything",
    }
    count = len(calls)
    execute(read_mailbox)
    assert len(calls) == count  # Terminal reentry never replays either read.


def test_catalog_only_finish_is_not_a_successful_mailbox_answer(read_mailbox, monkeypatch):
    no_research(monkeypatch)

    async def finish(*args):
        return {"kind": "finish", "message": "No mailbox result"}

    monkeypatch.setattr(runtime, "generate", finish)
    status, history = execute(read_mailbox)
    assert status == "unverified"
    assert not any(body["method"] == "tools/call" for body in read_mailbox[-1])


@pytest.mark.parametrize("interrupted", [False, True])
def test_prepared_catalog_is_not_duplicated_and_dispatching_catalog_is_never_replayed(
    read_mailbox, monkeypatch, interrupted
):
    app, _, _, cfg, _, job_id, calls = read_mailbox
    no_research(monkeypatch)
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        profiles = runtime.gate(db, cfg, job)
        runtime.prepare_mail_catalogs(db, job, profiles)
        if interrupted:
            runtime.steps(db, job_id)[0].status = "dispatching"
        db.commit()

    async def finish(*args):
        return {"kind": "finish", "message": "Catalog only"}

    monkeypatch.setattr(runtime, "generate", finish)
    status, history = execute(read_mailbox)
    assert status == ("uncertain" if interrupted else "unverified")
    assert len(history) == 1
    assert bool(calls) is not interrupted


def test_revocation_at_final_catalog_boundary_blocks_all_remote_requests(read_mailbox, monkeypatch):
    app, _, _, _, identifier, _, calls = read_mailbox
    no_research(monkeypatch)
    original = runtime.invoke

    def revoke(*args):
        with app.state.sessions() as db:
            db.get(AgentPolicy, identifier).revision += 1
            db.commit()
        return original(*args)

    monkeypatch.setattr(runtime, "invoke", revoke)
    status, history = execute(read_mailbox)
    assert status == "failed" and not calls
    assert any(step.status == "failed" for step in history)


def test_native_gmail_never_gets_an_mcp_catalog_and_filesystem_mcp_is_not_mail():
    job = SimpleNamespace(goal="Welche neuen Mails gab es heute?", max_effects=0)
    gmail = SimpleNamespace(kind="gmail", name="Gmail", writes_enabled=False)
    profiles = {"native": (gmail, Rules(enabled=True, gmail_read=True, max_effects=0), {})}
    assert runtime.mail_read_job(job, profiles)
    assert runtime.mail_read_contracts(profiles, []) == {
        "source": "observed_untrusted_metadata",
        "interfaces": [],
        "schemas": {},
    }
    filesystem = SimpleNamespace(kind="mcp", name="Filesystem", writes_enabled=False)
    assert not runtime.mail_read_job(
        job,
        {
            "fs": (
                filesystem,
                Rules(enabled=True, max_effects=0, mcp_read_tools={"list_folders": SHA}),
                {},
            )
        },
    )


def test_contracts_survive_history_clipping_and_do_not_silently_truncate_schemas():
    contracts = {"schemas": {SHA: SCHEMA}, "interfaces": [{"name": "search_emails"}]}
    data = {
        "mail_read_contracts": contracts,
        "history": [
            {"sequence": i, "kind": "read", "document": {}, "result": {"text": "synthetic" * 10000}}
            for i in range(2)
        ],
    }
    fitted = fit(data, "Synthetic instruction", 24000)
    assert fitted["mail_read_contracts"] == contracts
    assert "truncated" in json.dumps(fitted["history"])


def test_non_mail_administration_keeps_initial_research(agent, monkeypatch):
    from test_agents import start

    job_id = start(agent)
    researched = []

    async def research(*args):
        researched.append(args[-1])

    async def finish(*args):
        return {"kind": "finish", "message": "Synthetic administration result"}

    monkeypatch.setattr(runtime, "research", research)
    monkeypatch.setattr(runtime, "generate", finish)
    asyncio.run(runtime.execute_agent(agent[0].state.sessions, agent[3], None, job_id))
    assert researched == [job_id]


def test_catalog_batch_cannot_exceed_total_step_budget(read_mailbox, monkeypatch):
    app, client, headers, cfg, identifier, _, calls = read_mailbox
    no_research(monkeypatch)
    with app.state.sessions() as db:
        first = db.get(Integration, identifier)
        rules = Rules(
            enabled=True, max_effects=0, max_steps=1, mcp_read_tools={"search_emails": SHA}
        )
        policy = db.get(AgentPolicy, identifier)
        policy.rules = rules.model_dump_json()
        policy.revision += 1
        other = Integration(
            name="Other mailbox",
            kind="mcp",
            enabled=True,
            config=first.config,
            last_check=first.last_check,
        )
        db.add(other)
        db.flush()
        db.add(
            AgentPolicy(
                integration_id=other.id,
                profile_revision=other.revision,
                rules=rules.model_dump_json(),
            )
        )
        db.commit()
    chat = client.post("/api/conversations", headers=headers, json={}).json()["id"]
    started = client.post(
        f"/api/conversations/{chat}/agent-runs",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "goal": "Welche neuen Mails gab es heute?",
            "research_allowed": True,
        },
    )
    assert started.status_code == 200, started.text
    case = (*read_mailbox[:5], started.json()["id"], calls)
    status, history = execute(case)
    assert status == "failed" and not calls
    assert not any(step.kind in {"read", "effect"} for step in history)


def test_oversized_observed_contract_fails_closed_instead_of_clipping_schema():
    schema = {"type": "object", "description": "synthetic " * 2000}
    sha = schema_digest(schema)
    profile = SimpleNamespace(kind="mcp", id="synthetic")
    rules = Rules(enabled=True, max_effects=0, mcp_read_tools={"search_emails": sha})
    step = SimpleNamespace(
        status="succeeded",
        document=json.dumps({"integration_id": profile.id, "tool": "mcp.catalog"}),
        result=json.dumps({"tools": [{"name": "search_emails", "input_schema": schema}]}),
    )
    with pytest.raises(ValueError, match="Kontextgrenze"):
        runtime.mail_read_contracts({profile.id: (profile, rules, {})}, [step])


def test_first_mail_model_payload_with_eight_complete_schemas_is_compact(read_mailbox, monkeypatch):
    import copy

    no_research(monkeypatch)
    measurements = []

    async def generate(factory, cfg, providers, job_id, instruction, data):
        sample = copy.deepcopy(data)
        profile_id = sample["interfaces"][0]["integration_id"]
        names = sorted(runtime.MAIL_READ_TOOLS)
        for padding in range(0, 1600, 25):
            schemas = {
                name: {
                    "type": "object",
                    "title": name,
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Synthetic field metadata. " * 15,
                        }
                    },
                    "description": "Synthetic catalog metadata. " * 5
                    + ("x" * padding if index == 0 else ""),
                }
                for index, name in enumerate(names)
            }
            hashes = {name: schema_digest(schema) for name, schema in schemas.items()}
            rules = Rules(enabled=True, max_effects=0, mcp_read_tools=hashes)
            profile = SimpleNamespace(kind="mcp", id=profile_id)
            step = SimpleNamespace(
                status="succeeded",
                document=json.dumps({"integration_id": profile_id, "tool": "mcp.catalog"}),
                result=json.dumps(
                    {
                        "tools": [
                            {"name": name, "input_schema": schema}
                            for name, schema in schemas.items()
                        ]
                    }
                ),
            )
            contracts = runtime.mail_read_contracts({profile_id: (profile, rules, {})}, [step])
            if len(runtime.encode(contracts).encode()) >= 7100:
                break
        assert 7100 <= len(runtime.encode(contracts).encode()) < 7200
        sample["mail_read_contracts"] = contracts
        sample["interfaces"][0]["rules"]["mcp_read_tools"] = hashes
        fitted = fit(sample, instruction, cfg.context_limit)
        assert fitted["mail_read_contracts"] == contracts
        assert len(contracts["schemas"]) == 8
        assert all(contracts["schemas"][hashes[name]] == schemas[name] for name in names)
        content_bytes = len(instruction.encode()) + len(runtime.encode(fitted).encode())
        assert content_bytes <= 14000
        measurements.append(content_bytes)
        return {"kind": "finish", "message": "Synthetic catalog size proof"}

    monkeypatch.setattr(runtime, "generate", generate)
    status, _ = execute(read_mailbox)
    assert status == "unverified" and len(measurements) == 1
