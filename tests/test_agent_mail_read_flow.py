"""Real shared MCP read dispatch with synthetic mailbox wire and no account data."""

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from hub import agent_runtime as runtime
from hub import agent_tools
from hub.agent_clock import freeze_clock
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
def read_mailbox(mailbox, monkeypatch, request):
    app, client, headers, cfg, identifier = mailbox
    scenario = getattr(request, "param", {})
    schemas = scenario.get("schemas", {"search_emails": SCHEMA})
    with app.state.sessions() as db:
        row = db.get(Integration, identifier)
        row.last_check = json.dumps(
            {
                "revision": row.revision,
                "status": "succeeded",
                "result": {
                    "tools": [
                        {"name": name, "input_schema": schema} for name, schema in schemas.items()
                    ]
                },
            }
        )
        db.add(
            AgentPolicy(
                integration_id=identifier,
                profile_revision=row.revision,
                rules=Rules(
                    enabled=True,
                    max_effects=0,
                    mcp_read_tools={
                        name: schema_digest(schema) for name, schema in schemas.items()
                    },
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
            "goal": scenario.get("goal", "Welche neuen Mails gab es heute?"),
            "research_allowed": True,
        },
    )
    assert started.status_code == 200, started.text
    if "clock_at" in scenario:
        with app.state.sessions() as db:
            job = db.get(AgentJob, started.json()["id"])
            bindings = json.loads(job.bindings)
            bindings["clock"] = freeze_clock(
                "Europe/Berlin", datetime.fromisoformat(scenario["clock_at"]).timestamp()
            )
            job.bindings = json.dumps(bindings)
            db.commit()
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
                        *[
                            {"name": name, "inputSchema": schema}
                            for name, schema in schemas.items()
                        ],
                        {
                            "name": "delete_everything",
                            "inputSchema": {"type": "object"},
                            "description": "UNGRANTED TOOL MUST NOT REACH MODEL",
                        },
                    ]
                },
            )
        assert body["method"] == "tools/call"
        if body["params"]["name"] in {"get_status", "list_folders"}:
            return response(
                request,
                {
                    "isError": False,
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                scenario["status"]
                                if body["params"]["name"] == "get_status"
                                else scenario["folders"],
                                ensure_ascii=False,
                            ),
                        }
                    ],
                },
            )
        assert body["params"] == {
            "name": scenario.get("expected_query_tool", "search_emails"),
            "arguments": scenario.get(
                "expected_query_arguments",
                {"query": "", "since_days": scenario.get("since_days", 0)},
            ),
        }
        return response(
            request,
            {
                "isError": False,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(scenario["query_payload"], ensure_ascii=False)
                        if "query_payload" in scenario
                        else "Synthetic private mail; inert data",
                    }
                ],
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
        assert "mcp.catalog" not in data["tools"]
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
    assert status == "failed"
    assert sum(step.kind == "feedback" for step in history) == 2
    assert not any(body["method"] == "tools/call" for body in read_mailbox[-1])


@pytest.mark.parametrize(
    "read_mailbox",
    [
        {
            "goal": "Welche Mails gab es diese Woche?",
            "clock_at": "2026-10-20T12:00:00+00:00",
            "schemas": {
                "get_status": {"type": "object", "properties": {}},
                "search_emails": SCHEMA,
            },
            "status": [
                {"name": "Ordner äöü " + str(i), "total": i, "unread": i} for i in range(200)
            ],
            "since_days": 1,
        }
    ],
    indirect=True,
)
def test_weekly_multistep_mail_context_remains_bounded_after_large_status(
    read_mailbox, monkeypatch
):
    no_research(monkeypatch)
    identifier = read_mailbox[4]
    observed = []

    async def generate(factory, cfg, providers, job_id, instruction, data):
        # This is the actual fitted input supplied by the shared execution loop,
        # including a large intermediate read, not a separate fabricated payload.
        assert len(instruction.encode()) + len(runtime.encode(data).encode()) <= 14000
        assert data["clock"]["week_start"] and data["clock"]["week_end_exclusive"]
        assert data["clock"]["today"] == "2026-10-20"
        assert data["clock"]["week_start"].startswith("2026-10-19T00:00:00")
        assert data["clock"]["week_end_exclusive"].startswith("2026-10-26T00:00:00")
        contracts = data["mail_read_contracts"]
        assert contracts["schemas"][SHA] == SCHEMA
        observed.append(data)
        if len(observed) == 2:
            projected = data["history"][-1]["result"]["response"]["content"][0]
            assert projected["folder_count"] == 200 and projected["folders_omitted"] == 192
            assert len(projected["folders"]) == 8
        if len(observed) <= 2:
            name = "get_status" if len(observed) == 1 else "search_emails"
            return {
                "kind": "tool",
                "integration_id": identifier,
                "tool": "mcp.call",
                "arguments": {
                    "name": name,
                    "schema_sha256": next(
                        tool["schema_sha256"]
                        for tool in contracts["interfaces"][0]["tools"]
                        if tool["name"] == name
                    ),
                    "arguments": {} if name == "get_status" else {"query": "", "since_days": 1},
                },
                "message": "Synthetic bounded weekly read",
            }
        return {"kind": "finish", "message": "Synthetic weekly answer; broad filter is bounded"}

    monkeypatch.setattr(runtime, "generate", generate)
    status, history = execute(read_mailbox)
    assert status == "observed" and len(observed) == 3
    reads = [json.loads(step.document) for step in history if step.kind == "read"]
    assert [step.get("arguments", {}).get("name") for step in reads] == [
        None,
        "get_status",
        "search_emails",
    ]
    assert not any(step.kind in {"effect", "research"} for step in history)
    assert len(history[1].result.encode()) > 7000  # Durable evidence is never clipped.


@pytest.mark.parametrize(
    "read_mailbox",
    [
        {
            "goal": "Welche Mails gab es diese Woche ?",
            "clock_at": "2026-10-20T12:00:00+00:00",
            "schemas": {
                "get_status": {"type": "object", "properties": {}},
                "search_emails": SCHEMA,
            },
            "status": [
                {"name": "Synthetic folder " + str(i), "total": i, "unread": 0} for i in range(200)
            ],
            "since_days": 2,
            "query_payload": {
                "messages": [
                    {
                        "subject": ("Earlier prefix " if i < 10 else "Within currentHeader ")
                        + str(i)
                        + " Ä" * 70,
                        "sender": "Synthetic sender " + "字" * 50,
                        "received": "2026-10-18T21:59:00+00:00"
                        if i < 10
                        else "2026-10-18T22:15:00+00:00",
                        "uid": i,
                        "folder": "INBOX",
                        "message_id": "synthetic-id-" + str(i),
                    }
                    for i in range(20)
                ],
                "truncated": False,
            },
        }
    ],
    indirect=True,
)
def test_real_mail_dispatch_large_results_cannot_finish_as_false_empty_overview(
    read_mailbox, monkeypatch
):
    no_research(monkeypatch)
    app, client, _, _, identifier, job_id, _ = read_mailbox
    turns = []

    async def generate(factory, cfg, providers, job_id, instruction, data):
        assert len(instruction.encode()) + len(runtime.encode(data).encode()) <= 14000
        assert "calendar_prefilter_dates" in instruction
        assert (
            data["mail_read_progress"]["mail_evidence"]["calendar_prefilter_dates"]["week"]
            == "2026-10-18"
        )
        turns.append(data)
        if len(turns) == 3:
            evidence = data["mail_read_progress"]["mail_evidence"]
            assert len(runtime.encode(evidence).encode()) <= 1500
            view = evidence["query_receipts"][0]
            assert view["messages"][0]["subject"].startswith("Within currentHeader ")
            assert view["within_window_count"] == view["outside_window_count"] == 10
            assert not view["completeness_verified"] and view["messages_omitted"] > 0
            return {"kind": "finish", "message": "Keine Mails gefunden."}
        name = "get_status" if len(turns) == 1 else "search_emails"
        tools = data["mail_read_contracts"]["interfaces"][0]["tools"]
        return {
            "kind": "tool",
            "integration_id": identifier,
            "tool": "mcp.call",
            "arguments": {
                "name": name,
                "schema_sha256": next(t["schema_sha256"] for t in tools if t["name"] == name),
                "arguments": {} if name == "get_status" else {"query": "", "since_days": 2},
            },
            "message": "Synthetic actual read",
        }

    monkeypatch.setattr(runtime, "generate", generate)
    status, history = execute(read_mailbox)
    assert status == "observed" and len(turns) == 3
    response = client.get("/api/agent-runs/" + job_id).json()
    assert "Keine Mails gefunden" not in response["summary"]
    assert (
        "Within currentHeader" in response["summary"]
        and "Earlier prefix" not in response["summary"]
    )
    assert "keine Vollständigkeit" in response["summary"] and "begrenzt" in response["summary"]
    actual_query = next(
        step
        for step in history
        if json.loads(step.document).get("arguments", {}).get("name") == "search_emails"
    )
    assert (
        len(json.loads(json.loads(actual_query.result)["response"]["content"][0])["messages"]) == 20
    )
    assert not any(step.kind in {"effect", "research"} for step in history)


@pytest.mark.parametrize("timeout", [False, True])
def test_failed_local_mail_planning_has_safe_reason_and_terminal_job(
    read_mailbox, monkeypatch, timeout
):
    from hub.db import Run

    no_research(monkeypatch)
    app, client, _, _, _, job_id, _ = read_mailbox
    private_marker = "SYNTHETIC_PRIVATE_PROVIDER_BODY_MUST_STAY_OUT_OF_RECEIPTS"

    async def fail(factory, cfg, providers, run_id):
        with factory() as db:
            run = db.get(Run, run_id)
            run.status = "failed"
            run.error = (
                "Provider hat zu lange keine Daten geliefert. Der bisherige Text bleibt erhalten; "
                "bitte erneut versuchen."
                if timeout
                else private_marker
            )
            db.commit()

    monkeypatch.setattr("hub.execution.execute_run", fail)
    status, history = execute(read_mailbox)
    assert status == "failed"
    reason = "local_model_timeout" if timeout else "local_model_failed"
    assert json.loads(history[-1].document) == {"type": "AgentPlanningError", "reason": reason}
    assert json.loads(next(step for step in history if step.kind == "model").result) == {
        "reason": reason
    }
    public_job = client.get("/api/agent-runs/" + job_id).json()
    assert "neue Anfrage" in public_job["summary"]
    assert private_marker not in json.dumps(public_job)
    with app.state.sessions() as db:
        assert db.get(AgentJob, job_id).status not in runtime.ACTIVE


@pytest.mark.parametrize(
    "read_mailbox",
    [
        {
            "goal": "Welche Mails gab es diese Woche?",
            "schemas": {
                "list_folders": {"type": "object", "properties": {}},
                "search_emails": SCHEMA,
            },
            "folders": [
                {"name": f"Other folder {i}", "flags": [], "selectable": True} for i in range(200)
            ]
            + [
                {"name": "Observed all-mail name", "flags": ["\\All"], "selectable": True},
                {"name": "INBOX", "flags": ["\\Inbox"], "selectable": True},
            ],
        }
    ],
    indirect=True,
)
def test_folder_metadata_is_structured_and_repeat_proposal_never_redispatches(
    read_mailbox, monkeypatch
):
    import hashlib

    no_research(monkeypatch)
    app, _, _, cfg, identifier, job_id, calls = read_mailbox
    decisions = []

    async def generate(factory, cfg, providers, job_id, instruction, data):
        decisions.append(data)
        tools = data["mail_read_contracts"]["interfaces"][0]["tools"]
        assert data["mail_read_progress"]["next_action"] == (
            "answer_or_query" if len(decisions) == 4 else "query_messages"
        )
        if len(decisions) in {2, 3}:
            folder_step = next(
                s
                for s in data["history"]
                if s["document"].get("arguments", {}).get("name") == "list_folders"
            )
            projected = folder_step["result"]["response"]["content"][0]
            assert projected["model_projection"] == "folder_catalog"
            assert projected["folder_count"] == 202 and projected["folders_omitted"] == 194
            assert [f["name"] for f in projected["folders"][:2]] == [
                "Observed all-mail name",
                "INBOX",
            ]
            assert projected["folders"][0]["flags"] == ["\\All"]
            assert projected["folders"][1]["selectable"] is True
            assert data["mail_read_progress"]["folder_choices"] == [
                {"integration_id": identifier, **folder} for folder in projected["folders"][:2]
            ]
            assert all(
                p["tool"] in {"mcp.catalog", "list_folders"}
                for p in data["mail_read_progress"]["successful_preparations"]
            )
        if len(decisions) == 3:
            assert (
                data["history"][-1]["document"]["issues"][0]["type"]
                == "preparation_already_observed"
            )
        if len(decisions) == 4:
            return {"kind": "finish", "message": "Synthetic actual mailbox answer"}
        name = "list_folders" if len(decisions) <= 2 else "search_emails"
        return {
            "kind": "tool",
            "integration_id": identifier,
            "tool": "mcp.call",
            "arguments": {
                "name": name,
                "schema_sha256": next(t["schema_sha256"] for t in tools if t["name"] == name),
                "arguments": {} if name == "list_folders" else {"query": "", "since_days": 0},
            },
            "message": "Synthetic read",
        }

    monkeypatch.setattr(runtime, "generate", generate)
    status, history = execute(read_mailbox)
    assert status == "observed" and len(decisions) == 4
    assert [call["params"]["name"] for call in calls if call["method"] == "tools/call"] == [
        "list_folders",
        "search_emails",
    ]
    folder_step = next(
        s
        for s in history
        if s.kind == "read"
        and json.loads(s.document).get("arguments", {}).get("name") == "list_folders"
    )
    raw = json.loads(folder_step.result)["response"]["content"][0]
    assert len(json.loads(raw)) == 202
    projected = decisions[1]["history"][-1]["result"]["response"]["content"][0]
    assert projected["full_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    # A prepared duplicate left by an older worker cannot bypass the same guard.
    before = len(calls)
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        job.status = "running"
        duplicate = runtime.record(db, job, "read", json.loads(folder_step.document))
        sequence = duplicate.sequence
        db.commit()
    with pytest.raises(PermissionError, match="nicht erneut"):
        runtime.dispatch(app.state.sessions, cfg, job_id, sequence)
    assert len(calls) == before


def test_preparation_freshness_resets_only_at_human_input():
    document = {
        "integration_id": "account-one",
        "tool": "mcp.call",
        "arguments": {"name": "get_status", "arguments": {}, "schema_sha256": "a" * 64},
    }
    observed = SimpleNamespace(
        sequence=1, kind="read", status="succeeded", document=json.dumps(document)
    )
    assert runtime.repeated_mail_preparation([observed], document) == 1
    different = {**document, "integration_id": "account-two"}
    assert runtime.repeated_mail_preparation([observed], different) is None
    feedback = SimpleNamespace(sequence=2, kind="feedback", status="succeeded", document="{}")
    assert runtime.repeated_mail_preparation([observed, feedback], document) == 1
    human = SimpleNamespace(sequence=3, kind="input", status="succeeded", document="{}")
    assert runtime.repeated_mail_preparation([observed, feedback, human], document) is None


def test_mail_context_exhaustion_has_safe_specific_terminal_reason(read_mailbox, monkeypatch):
    from hub.agent_context import AgentContextLimitError

    no_research(monkeypatch)

    async def exhausted(*args):
        raise AgentContextLimitError("SYNTHETIC_PRIVATE_MODEL_CONTENT_MUST_NOT_BE_REPORTED")

    monkeypatch.setattr(runtime, "generate", exhausted)
    status, history = execute(read_mailbox)
    assert status == "failed"
    assert json.loads(history[-1].document) == {
        "type": "AgentContextLimitError",
        "reason": "local_context_limit",
    }
    app, client, _, _, _, job_id, _ = read_mailbox
    response = client.get("/api/agent-runs/" + job_id).json()
    assert "Modellkontext" in response["summary"]
    assert "SYNTHETIC_PRIVATE_MODEL_CONTENT" not in json.dumps(response)


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
    assert status == ("uncertain" if interrupted else "failed")
    assert sum(step.kind == "read" for step in history) == 1
    assert sum(step.kind == "feedback" for step in history) == (0 if interrupted else 2)
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
    phases = []

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
        phases.append("first")
        fitted = fit(sample, instruction, cfg.context_limit, max_bytes=14000)
        assert fitted["mail_read_contracts"] == contracts
        assert len(contracts["schemas"]) == 8
        assert all(contracts["schemas"][hashes[name]] == schemas[name] for name in names)
        content_bytes = len(instruction.encode()) + len(runtime.encode(fitted).encode())
        assert content_bytes <= 14000
        # Regression: the next decision previously ballooned to 23 KB after the
        # 100-folder get_status result. Exact contracts and authority stay intact.
        step.sequence, step.kind = 1, "read"
        status_step = SimpleNamespace(
            kind="read",
            status="succeeded",
            sequence=3,
            document=json.dumps(
                {
                    "integration_id": profile_id,
                    "tool": "mcp.call",
                    "arguments": {
                        "name": "get_status",
                        "arguments": {},
                        "schema_sha256": hashes["get_status"],
                    },
                }
            ),
            result=json.dumps(
                {
                    "response": {
                        "content": [
                            json.dumps(
                                [
                                    {"name": f"Synthetic folder {i}", "total": i, "unread": 0}
                                    for i in range(100)
                                ]
                            )
                        ]
                    }
                }
            ),
        )
        profiles = {profile_id: (profile, rules, {})}
        sample["history"].append(
            {
                "kind": "read",
                "status": "succeeded",
                "sequence": 3,
                "document": json.loads(status_step.document),
                "result": runtime.mail_history_result(status_step, profiles),
            }
        )
        sample["mail_read_progress"] = runtime.mail_progress(
            [step, status_step], profiles, sample["clock"], sample["goal"]
        )
        phases.append("status")
        fitted_next = fit(sample, instruction, cfg.context_limit, max_bytes=14000)
        assert fitted_next["mail_read_contracts"] == contracts
        assert fitted_next["interfaces"] == sample["interfaces"]
        assert len(instruction.encode()) + len(runtime.encode(fitted_next).encode()) <= 14000
        phases.append("status_fitted")
        query_step = SimpleNamespace(
            kind="read",
            status="succeeded",
            sequence=5,
            document=json.dumps(
                {
                    "integration_id": profile_id,
                    "tool": "mcp.call",
                    "arguments": {
                        "name": "search_emails",
                        "schema_sha256": hashes["search_emails"],
                        "arguments": {"query": ""},
                    },
                }
            ),
            result=json.dumps(
                {
                    "response": {
                        "content": [
                            json.dumps(
                                {
                                    "messages": [
                                        {
                                            "subject": "Actual typed header " + "字" * 100,
                                            "sender": "Synthetic " + "Ä" * 100,
                                            "received": sample["clock"]["request_at"],
                                            "folder": "INBOX",
                                            "uid": i,
                                        }
                                        for i in range(20)
                                    ]
                                }
                            )
                        ]
                    }
                }
            ),
        )
        sample["history"].append(
            {
                "kind": "read",
                "status": "succeeded",
                "sequence": 5,
                "document": json.loads(query_step.document),
                "result": runtime.mail_history_result(query_step, profiles),
            }
        )
        sample["mail_read_progress"] = runtime.mail_progress(
            [step, status_step, query_step], profiles, sample["clock"], sample["goal"]
        )
        phases.append(("query", len(runtime.encode(sample["mail_read_progress"]).encode())))
        final = fit(sample, instruction, cfg.context_limit, max_bytes=14000)
        assert final["interfaces"] == sample["interfaces"]
        assert final["mail_read_contracts"] == contracts
        typed = final["mail_read_progress"]["mail_evidence"]["query_receipts"][0]
        assert typed["messages"][0]["subject"].startswith("Actual typed header ")
        assert "excerpt" not in typed and len(contracts["schemas"]) == 8
        assert len(instruction.encode()) + len(runtime.encode(final).encode()) <= 14000
        measurements.append(content_bytes)
        # This context-only fixture has no actual current message query.
        # A genuine missing-detail question preserves the one-turn size measurement.
        return {"kind": "ask", "message": "Which missing synthetic search detail?"}

    monkeypatch.setattr(runtime, "generate", generate)
    status, trace = execute(read_mailbox)
    assert status == "awaiting_input" and len(measurements) == 1, (phases, trace[-1].document)
