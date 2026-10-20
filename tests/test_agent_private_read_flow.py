"""Shared private archive loop using real typed dispatch and synthetic HTTP receipts."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from hub import agent_runtime as runtime
from hub import agent_tools
from hub.agent_context import fit
from hub.agent_models import AgentJob, AgentPolicy
from hub.integrations import Integration

pytest_plugins = ["test_agents", "test_agent_mail_read_flow"]


@pytest.fixture
def archive(agent, monkeypatch):
    app, client, headers, cfg, identifier, chat, *_ = agent
    calls = []
    body = {"count": 1, "results": [{"id": 42, "title": "Synthetic contract", "tags": []}]}
    scenario = {"status": 200, "body": body, "revoke": False}
    original = httpx.Client

    def pin(*args):
        if scenario["revoke"]:
            with app.state.sessions() as db:
                policy = db.get(AgentPolicy, identifier)
                policy.revision += 1
                db.commit()
        return "https://192.168.50.20", {}, {}

    def wire(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Token synthetic-write-token"
        return httpx.Response(scenario["status"], json=scenario["body"])

    monkeypatch.setattr(agent_tools, "pinned_target", pin)
    monkeypatch.setattr(
        agent_tools.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(wire), **kw),
    )

    async def forbidden(*args):
        pytest.fail("Private document data must not initiate public research")

    monkeypatch.setattr(runtime, "research", forbidden)

    def start(goal="Welche Dokumente gibt es in Paperless?", **extra):
        response = client.post(
            f"/api/conversations/{chat}/agent-runs",
            headers=headers,
            json={"request_id": str(uuid4()), "goal": goal, "research_allowed": True, **extra},
        )
        assert response.status_code == 200, response.text
        return response.json()["id"]

    return agent, start, scenario, calls


def execute(case, job_id):
    app, client, _, cfg, *_ = case[0]
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    return client.get(f"/api/agent-runs/{job_id}").json()


def decision(identifier, **arguments):
    return {
        "kind": "tool",
        "integration_id": identifier,
        "tool": "paperless.read",
        "arguments": arguments,
        "message": "Read authorized synthetic archive",
    }


@pytest.mark.parametrize(
    "goal",
    [
        "Welche Dokumente gibt es in Paperless?",
        "Gib mir meine letzten Rechnungen",
        "Wie lautet meine Kundennummer im Vertrag?",
        "Und dieses?",
    ],
)
def test_private_archive_uses_typed_read_no_research_or_confirmation_and_real_receipt(
    archive, monkeypatch, goal
):
    agent, start, _, calls = archive
    app, _, _, cfg, identifier, *_ = agent
    job_id = start(goal)
    phases = []

    async def generate(factory, cfg, providers, current_job, instruction, data):
        assert "LOCAL_ONLY" in instruction and "keine Endpunkte erfinden" in instruction
        assert data["read_only"] and set(data["tools"]) == {"paperless.read"}
        assert len(instruction.encode()) + len(runtime.encode(data).encode()) <= 14000
        phases.append(data)
        if len(phases) == 1:
            assert data["allow_finish"] is False
            return decision(identifier, operation="search", query="Synthetic contract")
        assert data["allow_finish"] is True
        observed = data["latest_observation"]["result"]
        assert observed["model_projection"] == "paperless_query_receipt"
        assert observed["documents"][0]["id"] == 42
        assert observed["documents"][0]["title"] == "Synthetic contract"
        return {"kind": "finish", "message": "Document 42: Synthetic contract (bounded search)."}

    monkeypatch.setattr(runtime, "generate", generate)
    result = execute(archive, job_id)
    assert result["status"] == "observed" and len(calls) == 1
    assert len(phases) == 2
    assert calls[0].url.params["query"] == "Synthetic contract"
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert job.max_effects == 0 and json.loads(job.bindings)["read_only"]
        assert db.get(Integration, identifier).writes_enabled  # Existing global rights preserved.
        assert not any(s.kind in {"effect", "research", "input"} for s in runtime.steps(db, job_id))


def test_premature_finish_receives_bounded_feedback_then_must_retrieve(archive, monkeypatch):
    agent, start, _, calls = archive
    job_id = start()
    phases = []

    async def generate(*args):
        data = args[-1]
        phases.append(data)
        if len(phases) == 1:
            return {"kind": "finish", "message": "Invented answer without reading"}
        if len(phases) == 2:
            assert data["allow_finish"] is False
            assert any(h["kind"] == "feedback" for h in data["history"])
            return decision(agent[4], operation="search")
        assert data["allow_finish"] is True
        return {"kind": "finish", "message": "Observed Synthetic contract 42"}

    monkeypatch.setattr(runtime, "generate", generate)
    result = execute(archive, job_id)
    assert result["status"] == "observed" and len(calls) == 1
    assert "Invented answer" not in result["summary"]


def test_repeated_premature_finish_cannot_claim_success_or_loop_forever(archive, monkeypatch):
    _, start, _, calls = archive
    count = []

    async def finish(*args):
        count.append(True)
        return {"kind": "finish", "message": "Invented"}

    monkeypatch.setattr(runtime, "generate", finish)
    result = execute(archive, start())
    assert result["status"] == "failed" and len(count) == 3 and not calls
    assert sum(s["kind"] == "feedback" for s in result["steps"]) == 2


@pytest.mark.parametrize("failure", ["authentication", "malformed", "revoked"])
def test_failed_or_revoked_reads_cannot_finish_or_replay(archive, monkeypatch, failure):
    agent, start, scenario, calls = archive
    if failure == "authentication":
        scenario["status"] = 401
        scenario["body"] = {"private": "Never surface synthetic private server error"}
    elif failure == "malformed":
        scenario["body"] = {"count": 1, "results": "wrong"}
    else:
        scenario["revoke"] = True
    requested = []

    async def generate(*args):
        requested.append(True)
        return decision(agent[4], operation="search")

    monkeypatch.setattr(runtime, "generate", generate)
    result = execute(archive, start())
    assert result["status"] not in {"observed", "succeeded"}
    assert len(requested) == 1 and len(calls) == (0 if failure == "revoked" else 1)
    assert "private server error" not in json.dumps(result)


def test_full_large_ocr_receipt_kept_but_planner_remains_bounded(archive, monkeypatch):
    agent, start, scenario, calls = archive
    scenario["body"] = {"id": 42, "title": "Synthetic contract", "content": "字" * 100001}
    job_id = start("Fasse Dokument 42 zusammen")
    phases = []

    async def generate(*args):
        instruction, data = args[-2:]
        assert len(instruction.encode()) + len(runtime.encode(data).encode()) <= 14000
        phases.append(data)
        if len(phases) == 1:
            return decision(agent[4], operation="document", document_id=42)
        projected = data["latest_observation"]["result"]
        assert projected["documents"][0]["id"] == 42
        assert projected["documents"][0]["content_truncated"]
        assert projected["documents"][0]["content"].startswith("字")
        assert projected["partial_view"]
        return {"kind": "finish", "message": "Document 42, excerpt only; OCR truncated."}

    monkeypatch.setattr(runtime, "generate", generate)
    result = execute(archive, job_id)
    assert result["status"] == "observed" and len(calls) == 1
    with agent[0].state.sessions() as db:
        original = json.loads(next(s for s in runtime.steps(db, job_id) if s.kind == "read").result)
        assert len(original["data"]["content"]) == 100000
        assert original["data"]["content_truncated"]


def test_model_cannot_smuggle_generic_http_change_into_private_read(archive, monkeypatch):
    agent, start, _, calls = archive

    async def write(*args):
        return {
            "kind": "tool",
            "integration_id": agent[4],
            "tool": "http",
            "arguments": {
                "method": "PATCH",
                "path": "/api/documents/42/",
                "body": {"title": "Bad"},
            },
            "message": "Pretend reading",
        }

    monkeypatch.setattr(runtime, "generate", write)
    result = execute(archive, start())
    assert result["status"] == "failed" and not calls
    assert not any(s["kind"] == "effect" for s in result["steps"])


@pytest.mark.parametrize(
    "goal",
    [
        "Ändere das Dokument im Archiv",
        "Lösche Dokument 42",
        "Update Paperless",
        "Benenne das synthetische Dokument um und prüfe den gespeicherten Titel.",
    ],
)
def test_clear_administration_keeps_existing_path_and_effect_budget(agent, goal):
    app, client, headers, _, _, chat, *_ = agent
    response = client.post(
        f"/api/conversations/{chat}/agent-runs",
        headers=headers,
        json={"request_id": str(uuid4()), "goal": goal},
    )
    assert response.status_code == 200
    with app.state.sessions() as db:
        job = db.get(AgentJob, response.json()["id"])
        assert job.max_effects == 2 and not json.loads(job.bindings)["read_only"]


def test_fit_retains_complete_prior_refs_and_typed_latest_ocr_beside_full_authority():
    observation = {
        "model_projection": "paperless_query_receipt",
        "full_sha256": "a" * 64,
        "documents": [{"id": 42, "title": "Synthetic", "content": "Private OCR"}],
    }
    prior = [{"source_id": "agent-read:job:7", "integration_id": "archive", "result": observation}]
    payload = {
        "goal": "Summarize the same document",
        "interfaces": [{"id": "archive", "rules": {"GET": True}}],
        "tools": {"paperless.read": agent_tools.PaperlessCall.model_json_schema()},
        "private_read_evidence": True,
        "prior_read_results": prior,
        "private_context": [{"content": "x" * 40000}],
        "history": [
            {
                "kind": "read",
                "sequence": 7,
                "document": {"tool": "paperless.read"},
                "result": observation,
            }
        ],
    }
    fitted = fit(payload, "Private local reader", 24000, max_bytes=14000)
    assert fitted["prior_read_results"] == prior
    assert fitted["latest_observation"]["result"] == observation
    assert fitted["interfaces"] == payload["interfaces"] and fitted["tools"] == payload["tools"]


def test_eight_full_mail_contracts_prior_receipts_and_typed_thread_fit_together():
    from types import SimpleNamespace

    from hub.agent_clock import freeze_clock
    from hub.agent_mail_read import model_result
    from hub.mcp_client import schema_digest

    identifier = "00000000-0000-0000-0000-000000000007"
    names = sorted(runtime.MAIL_READ_TOOLS)
    for padding in range(0, 1600, 25):
        schemas = {
            name: {
                "type": "object",
                "title": name,
                "properties": {
                    "query": {"type": "string", "description": "Synthetic metadata. " * 20}
                },
                "description": "Synthetic catalog. " * 8 + ("x" * padding if i == 0 else ""),
            }
            for i, name in enumerate(names)
        }
        hashes = {name: schema_digest(schema) for name, schema in schemas.items()}
        rules = agent_tools.Rules(enabled=True, max_effects=0, mcp_read_tools=hashes)
        catalog = SimpleNamespace(
            status="succeeded",
            document=runtime.encode({"integration_id": identifier, "tool": "mcp.catalog"}),
            result=runtime.encode(
                {"tools": [{"name": n, "input_schema": schema} for n, schema in schemas.items()]}
            ),
        )
        contracts = runtime.mail_read_contracts(
            {identifier: (SimpleNamespace(kind="mcp", id=identifier), rules, {})}, [catalog]
        )
        if len(runtime.encode(contracts).encode()) >= 7100:
            break
    assert 7100 <= len(runtime.encode(contracts).encode()) < 7200
    receipt = {
        "response": {
            "content": [
                runtime.encode(
                    [
                        {
                            "message_id": "<original@example.test>",
                            "folder": "INBOX",
                            "uid": 7,
                            "subject": "Original",
                            "sender": "Synthetic sender",
                            "references": "<root@example.test>",
                            "answered": True,
                        },
                        {
                            "message_id": "<reply@example.test>",
                            "in_reply_to": "<original@example.test>",
                            "folder": "Gesendet",
                            "uid": 8,
                            "subject": "Reply",
                            "sender": "Synthetic account",
                        },
                    ]
                )
            ]
        }
    }
    current = model_result("get_thread", receipt, max_bytes=1400, account_id=identifier)
    assert current and current["messages"]
    prior = [
        {
            "source_id": f"agent-read:source-job:{i}",
            "integration_id": identifier,
            "result_sha256": str(i) * 64,
            "label": "LOCAL_ONLY",
            "untrusted": True,
            "result": {
                "messages": [
                    {
                        "message_id": f"<prior-{i}@example.test>",
                        "uid": i,
                        "folder": "INBOX",
                        "account_id": identifier,
                    }
                ]
            },
        }
        for i in (1, 2)
    ]
    payload = {
        "allow_finish": True,
        "allow_ask": False,
        "allow_stop": True,
        "goal": "Auf welche dieser Mails habe ich schon geantwortet?",
        "clock": freeze_clock("Europe/Berlin"),
        "read_only": True,
        "interfaces": [
            {
                "integration_id": identifier,
                "kind": "mcp",
                "name": "Synthetic mailbox",
                "writes_enabled": False,
                "rules": rules.model_dump(),
            }
        ],
        "tools": {"mcp.call": agent_tools.MCPCall.model_json_schema()},
        "decision_schema": agent_tools.decision_envelope_schema(
            [identifier], ["mcp.call"], allow_ask=False, allow_stop=True
        ),
        "mail_read_contracts": contracts,
        "mail_read_progress": {"mailbox_queried": True, "next_action": "answer_or_query"},
        "prior_read_results": prior,
        "private_read_evidence": True,
        "private_context": [{"content": "Synthetic old conversation. " * 500}],
        "history": [
            {
                "kind": "read",
                "sequence": 7,
                "status": "succeeded",
                "document": {
                    "tool": "mcp.call",
                    "integration_id": identifier,
                    "arguments": {"name": "get_thread", "schema_sha256": hashes["get_thread"]},
                },
                "result": current,
            }
        ],
    }
    fitted = fit(payload, runtime.MAIL_READ_INSTRUCTION, 24000, max_bytes=14000)
    assert (
        len(runtime.MAIL_READ_INSTRUCTION.encode()) + len(runtime.encode(fitted).encode()) <= 14000
    )
    assert fitted["mail_read_contracts"] == contracts
    assert fitted["interfaces"] == payload["interfaces"]
    assert fitted["tools"] == payload["tools"]
    assert fitted["prior_read_results"] == prior
    assert fitted["latest_observation"]["result"] == current


@pytest.mark.parametrize("question", ["Fasse dieses Dokument zusammen", "Und dieses?"])
def test_followup_uses_revocable_actual_receipt_id_then_reads_document_content(
    archive, monkeypatch, question
):
    agent, start, scenario, calls = archive
    phase = []

    async def first(*args):
        phase.append(True)
        if len(phase) == 1:
            return decision(agent[4], operation="search", query="Synthetic contract")
        return {"kind": "finish", "message": "Found synthetic contract document 42."}

    monkeypatch.setattr(runtime, "generate", first)
    previous_id = start()
    assert execute(archive, previous_id)["status"] == "observed"
    scenario["body"] = {
        "id": 42,
        "title": "Synthetic contract",
        "content": "Synthetic OCR evidence",
    }
    phase.clear()

    async def followup(*args):
        data = args[-1]
        phase.append(data)
        assert data["read_only"] is True
        if len(phase) == 1:
            assert data["allow_finish"] is False
            prior = data["prior_read_results"]
            assert prior[0]["integration_id"] == agent[4]
            assert prior[0]["source_id"].startswith(f"agent-read:{previous_id}:")
            assert prior[0]["result"]["documents"][0]["id"] == 42
            assert prior[0]["result_sha256"]
            return decision(agent[4], operation="document", document_id=42)
        assert data["allow_finish"]
        assert (
            data["latest_observation"]["result"]["documents"][0]["content"]
            == "Synthetic OCR evidence"
        )
        return {"kind": "finish", "message": "Document 42 contains synthetic OCR evidence."}

    monkeypatch.setattr(runtime, "generate", followup)
    result = execute(archive, start(question))
    assert result["status"] == "observed"
    assert [r.url.path for r in calls] == ["/api/documents/", "/api/documents/42/"]


@pytest.mark.parametrize(
    "goal",
    [
        "Prüfe den Paperless Systemstatus",
        "Zeige die Paperless API Konfiguration",
        "Welche Paperless Version läuft?",
        "Ändere Dokument 42",
        "Update Paperless",
    ],
)
def test_explicit_readonly_administration_is_not_forced_into_document_reader(agent, goal):
    app, client, headers, _, _, chat, *_ = agent
    response = client.post(
        f"/api/conversations/{chat}/agent-runs",
        headers=headers,
        json={"request_id": str(uuid4()), "goal": goal, "read_only": True},
    )
    assert response.status_code == 200
    with app.state.sessions() as db:
        job = db.get(AgentJob, response.json()["id"])
        assert json.loads(job.bindings)["read_only"]
        assert not runtime.paperless_read_job(job, runtime.gate(db, agent[3], job))


def test_uncertain_effect_reconciliation_retains_generic_readonly_http_path(agent):
    app, _, _, cfg, _, chat, *_ = agent
    with app.state.sessions() as db:
        job = runtime.create_job(
            db,
            cfg,
            scope="conversation",
            owner_id=chat,
            conversation_id=chat,
            request_id=str(uuid4()),
            goal="Vergleiche den früheren Zustand",
            research_allowed=False,
            read_only=True,
            context=[
                {
                    "source_id": "agent-effect:earlier:1",
                    "revision": 1,
                    "label": "LOCAL_ONLY",
                    "content": "Earlier uncertain metadata operation",
                }
            ],
        )
        db.commit()
        profiles = runtime.gate(db, cfg, job)
        assert not runtime.paperless_read_job(job, profiles)
        assert json.loads(job.bindings)["read_only"]


_THREAD_SCHEMA = {
    "type": "object",
    "properties": {"uid": {"type": "integer"}, "folder": {"type": "string"}},
    "required": ["uid", "folder"],
    "additionalProperties": False,
}
_MAIL_SCENARIO = {
    "goal": "Welche Mails habe ich erhalten?",
    "schemas": {
        "search_emails": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "since_days": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        },
        "get_thread": _THREAD_SCHEMA,
    },
    "query_payload": {
        "messages": [
            {
                "uid": 7,
                "folder": "INBOX",
                "message_id": "<original@example.test>",
                "subject": "Synthetic original",
                "sender": "Synthetic sender",
            }
        ]
    },
}


@pytest.mark.parametrize("read_mailbox", [_MAIL_SCENARIO], indirect=True)
@pytest.mark.parametrize("invalid_first", [None, "stop", "invented_uid"])
def test_mail_followup_without_mail_keyword_uses_account_bound_prior_uid_then_actual_thread(
    read_mailbox, monkeypatch, invalid_first
):
    from hub.mcp_client import schema_digest

    app, client, headers, cfg, identifier, first_id, calls = read_mailbox
    seen = []

    async def no_research(*args):
        pytest.fail("Anaphoric mailbox follow-up must remain a private read")

    monkeypatch.setattr(runtime, "research", no_research)

    async def initial(*args):
        seen.append(True)
        if len(seen) == 1:
            return {
                "kind": "tool",
                "integration_id": identifier,
                "tool": "mcp.call",
                "arguments": {
                    "name": "search_emails",
                    "schema_sha256": schema_digest(_MAIL_SCENARIO["schemas"]["search_emails"]),
                    "arguments": {"query": "", "since_days": 0},
                },
                "message": "Read actual headers",
            }
        return {"kind": "finish", "message": "Observed synthetic original."}

    monkeypatch.setattr(runtime, "generate", initial)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, first_id))
    with app.state.sessions() as db:
        first = db.get(AgentJob, first_id)
        assert first.status == "observed"
        chat = first.conversation_id
    # The wire fixture retains this same private synthetic scenario object.
    _MAIL_SCENARIO.update(
        expected_query_tool="get_thread",
        expected_query_arguments={"uid": 7, "folder": "INBOX"},
        query_payload=[
            {
                "uid": 7,
                "folder": "INBOX",
                "message_id": "<original@example.test>",
                "subject": "Synthetic original",
                "answered": True,
            },
            {
                "uid": 8,
                "folder": "Gesendet",
                "message_id": "<reply@example.test>",
                "in_reply_to": "<original@example.test>",
                "subject": "Synthetic reply",
            },
        ],
    )
    try:
        response = client.post(
            f"/api/conversations/{chat}/agent-runs",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "goal": "Welche davon habe ich bereits beantwortet?",
                "research_allowed": True,
            },
        )
        assert response.status_code == 200, response.text
        followup_id = response.json()["id"]
        seen.clear()

        async def followup(*args):
            instruction, data = args[-2:]
            assert instruction == runtime.MAIL_READ_INSTRUCTION
            assert "research" not in data["tools"]
            assert len(instruction.encode()) + len(runtime.encode(data).encode()) <= 14000
            seen.append(data)
            if not data["allow_finish"]:
                assert not data["allow_finish"]
                assert not data["allow_stop"]
                candidate = json.loads(runtime.encode(data["ready_reads"]["decisions"][0]))
                assert candidate["integration_id"] == identifier
                assert candidate["arguments"]["arguments"] == {"uid": 7, "folder": "INBOX"}
                assert candidate["arguments"]["schema_sha256"] == schema_digest(_THREAD_SCHEMA)
                if len(seen) == 1 and invalid_first == "stop":
                    return {"kind": "stop", "message": "Ask for mail selection again"}
                if len(seen) == 1 and invalid_first == "invented_uid":
                    candidate["arguments"]["arguments"]["uid"] = 999
                return candidate
            assert data["allow_finish"]
            assert data["allow_stop"] and "ready_reads" not in data
            latest = data["latest_observation"]["result"]
            assert latest["model_projection"] == "mail_read_metadata"
            assert latest["messages"][0]["marked_answered"] is True
            assert latest["messages"][0]["account_id"] == identifier
            return {
                "kind": "finish",
                "message": "UID 7 is marked answered; sent relationship not verified.",
            }

        monkeypatch.setattr(runtime, "generate", followup)
        asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, followup_id))
        with app.state.sessions() as db:
            job = db.get(AgentJob, followup_id)
            assert job.status == "observed", job.summary
            assert not any(
                s.kind in {"effect", "research", "input"} for s in runtime.steps(db, followup_id)
            )
        assert [c["params"]["name"] for c in calls if c["method"] == "tools/call"] == [
            "search_emails",
            "get_thread",
        ]
    finally:
        # Keep the module fixture stable if pytest reuses this parameter object.
        _MAIL_SCENARIO.pop("expected_query_tool", None)
        _MAIL_SCENARIO.pop("expected_query_arguments", None)
        _MAIL_SCENARIO["query_payload"] = {
            "messages": [
                {
                    "uid": 7,
                    "folder": "INBOX",
                    "message_id": "<original@example.test>",
                    "subject": "Synthetic original",
                    "sender": "Synthetic sender",
                }
            ]
        }


@pytest.mark.parametrize("when", ["before", "after", "both"])
def test_private_archive_rejects_confirmation_before_and_after_reads_then_answers(
    archive, monkeypatch, when
):
    agent, start, _, calls = archive
    responses = []
    if when in {"before", "both"}:
        responses.append({"kind": "ask", "message": "Confirm reading the authorized archive?"})
    responses.append(decision(agent[4], operation="search"))
    if when in {"after", "both"}:
        responses.append({"kind": "ask", "message": "Confirm interpreting the actual results?"})
    responses.append({"kind": "finish", "message": "Document 42 found, limited to this search."})
    states = []

    async def generate(*args):
        data = args[-1]
        assert data["allow_ask"] is False and data["allow_stop"] is True
        states.append(data["allow_finish"])
        return responses.pop(0)

    monkeypatch.setattr(runtime, "generate", generate)
    result = execute(archive, start())
    assert result["status"] == "observed" and len(calls) == 1
    assert False in states and True in states
    assert not any(s["kind"] == "input" for s in result["steps"])
    assert sum(s["kind"] == "feedback" for s in result["steps"]) == (2 if when == "both" else 1)
    assert "Confirm" not in result["summary"]


@pytest.mark.parametrize("queried", [False, True])
def test_private_archive_can_stop_unverified_without_permission_question_or_invented_id(
    archive, monkeypatch, queried
):
    agent, start, _, calls = archive
    responses = ([decision(agent[4], operation="search")] if queried else []) + [
        {
            "kind": "stop",
            "message": "The requested exact identity is absent from available evidence.",
        },
    ]

    async def generate(*args):
        assert args[-1]["allow_stop"] and not args[-1]["allow_ask"]
        return responses.pop(0)

    monkeypatch.setattr(runtime, "generate", generate)
    result = execute(archive, start())
    assert result["status"] == "unverified" and len(calls) == int(queried)
    assert result["summary"].startswith("Anfrage nicht vollständig beantwortet: ")
    assert not any(s["kind"] in {"effect", "input", "feedback"} for s in result["steps"])


def test_repeated_private_confirmation_is_bounded_and_never_waits_for_user(archive, monkeypatch):
    _, start, _, calls = archive
    count = []

    async def ask(*args):
        count.append(True)
        return {"kind": "ask", "message": "Please confirm again."}

    monkeypatch.setattr(runtime, "generate", ask)
    result = execute(archive, start())
    assert result["status"] == "failed" and len(count) == 3 and not calls
    assert sum(s["kind"] == "feedback" for s in result["steps"]) == 2


def test_administrative_question_remains_askable_and_private_stop_is_rejected(archive, monkeypatch):
    _, start, _, calls = archive
    phases = []

    async def generate(*args):
        data = args[-1]
        assert data["allow_ask"] is True and data["allow_stop"] is False
        phases.append(True)
        if len(phases) == 1:
            return {"kind": "stop", "message": "Unavailable private terminal"}
        return {"kind": "ask", "message": "Which actual API configuration should be compared?"}

    async def disabled_research(factory, cfg, providers, job_id):
        with factory() as db:
            assert not db.get(AgentJob, job_id).research_allowed

    monkeypatch.setattr(runtime, "research", disabled_research)
    monkeypatch.setattr(runtime, "generate", generate)
    result = execute(
        archive, start("Prüfe die Paperless API Konfiguration", research_allowed=False)
    )
    assert result["status"] == "awaiting_input" and len(phases) == 2 and not calls
    assert sum(s["kind"] == "feedback" for s in result["steps"]) == 1


@pytest.mark.parametrize("read_mailbox", [_MAIL_SCENARIO], indirect=True)
@pytest.mark.parametrize("when", ["before", "after"])
def test_private_mail_rejects_ask_but_reads_current_messages_then_answers(
    read_mailbox, monkeypatch, when
):
    from hub.mcp_client import schema_digest

    app, _, _, cfg, identifier, job_id, calls = read_mailbox
    query = {
        "kind": "tool",
        "integration_id": identifier,
        "tool": "mcp.call",
        "arguments": {
            "name": "search_emails",
            "schema_sha256": schema_digest(_MAIL_SCENARIO["schemas"]["search_emails"]),
            "arguments": {"query": "", "since_days": 0},
        },
        "message": "Read authorized mailbox",
    }
    ask = {"kind": "ask", "message": "May I access the selected mailbox?"}
    responses = ([ask, query] if when == "before" else [query, ask]) + [
        {
            "kind": "finish",
            "message": "Actual bounded message evidence, reply coverage remains unknown.",
        },
    ]

    async def forbidden(*args):
        pytest.fail("Private mail never researches to obtain read permission")

    async def generate(*args):
        instruction, data = args[-2:]
        assert not data["allow_ask"] and data["allow_stop"]
        assert len(instruction.encode()) + len(runtime.encode(data).encode()) <= 14000
        return responses.pop(0)

    monkeypatch.setattr(runtime, "research", forbidden)
    monkeypatch.setattr(runtime, "generate", generate)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert job.status == "observed", job.summary
        assert sum(s.kind == "feedback" for s in runtime.steps(db, job_id)) == 1
    assert sum(c["method"] == "tools/call" for c in calls) == 1


@pytest.mark.parametrize("ready", [[], [{
    "kind": "tool", "integration_id": "synthetic", "tool": "mcp.call",
    "arguments": {"name": "read_email", "schema_sha256": "a" * 64,
                  "arguments": {"uid": 7, "folder": "INBOX"}},
    "message": "Read original identity",
}]])
def test_private_decision_flags_are_persisted_for_native_generation(archive, monkeypatch, ready):
    from hub.db import Run

    agent, start, _, _ = archive
    job_id = start()
    snapshots = []

    async def execute_run(factory, cfg, providers, run_id):
        with factory() as db:
            row = db.get(Run, run_id)
            snapshot = json.loads(row.context_snapshot)
            snapshots.append(snapshot["agent_generation"])
            row.status = "succeeded"
            db.commit()

    monkeypatch.setattr("hub.execution.execute_run", execute_run)
    monkeypatch.setattr(
        runtime, "execution_text", lambda *args: '{"kind":"stop","message":"Missing evidence"}'
    )
    result = asyncio.run(
        runtime.generate(
            agent[0].state.sessions,
            agent[3],
            None,
            job_id,
            "Synthetic private policy",
            {
                "allow_finish": False,
                "allow_ask": False,
                "allow_stop": True,
                "ready_reads": {"decisions": ready},
                "decision_schema": {},
                "tools": {"paperless.read": agent_tools.PaperlessCall.model_json_schema()},
                "interfaces": [{"integration_id": agent[4], "kind": "paperless", "rules": {}}],
            },
        )
    )
    assert result["kind"] == "stop"
    assert snapshots[0]["allow_finish"] is False
    assert snapshots[0]["allow_ask"] is False and snapshots[0]["allow_stop"] is True
    assert snapshots[0]["ready_reads"] == ready


@pytest.mark.parametrize("read_mailbox", [_MAIL_SCENARIO], indirect=True)
@pytest.mark.parametrize("queried", [False, True])
def test_private_mail_stop_remains_unverified_with_or_without_current_data(
    read_mailbox, monkeypatch, queried
):
    from hub.mcp_client import schema_digest

    app, _, _, cfg, identifier, job_id, calls = read_mailbox
    responses = (
        [
            {
                "kind": "tool",
                "integration_id": identifier,
                "tool": "mcp.call",
                "arguments": {
                    "name": "search_emails",
                    "schema_sha256": schema_digest(_MAIL_SCENARIO["schemas"]["search_emails"]),
                    "arguments": {"query": "", "since_days": 0},
                },
                "message": "Read permitted messages",
            }
        ]
        if queried
        else []
    ) + [
        {
            "kind": "stop",
            "message": "Available tools do not establish the requested exact identity.",
        },
    ]

    async def forbidden(*args):
        pytest.fail("Stopping a private read does not authorize public research")

    async def generate(*args):
        data = args[-1]
        assert not data["allow_ask"] and data["allow_stop"]
        return responses.pop(0)

    monkeypatch.setattr(runtime, "research", forbidden)
    monkeypatch.setattr(runtime, "generate", generate)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert job.status == "unverified"
        assert job.summary.startswith("Anfrage nicht vollständig beantwortet: ")
        assert not any(s.kind in {"effect", "input"} for s in runtime.steps(db, job_id))
    assert sum(c["method"] == "tools/call" for c in calls) == int(queried)
