"""Application-planned pinned-mailbox reads use the shared durable dispatch gates."""

import json

import pytest
from hub import agent_runtime as runtime
from hub.agent_models import AgentJob, AgentPolicy
from hub.integrations import Integration
from hub.mcp_client import schema_digest
from test_agent_mail_read_flow import execute, no_research

pytest_plugins = ["test_agent_mail_read_flow"]
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {"type": "string", "default": ""},
        "folder": {"type": "string", "default": "INBOX"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        "since_days": {"type": "integer", "minimum": 0},
        "unread_only": {"type": "boolean", "default": False},
        "has_attachment": {"type": "boolean", "default": False},
    },
}
ARGS = {
    "query": "",
    "folder": "INBOX",
    "limit": 20,
    "since_days": 2,
    "unread_only": False,
    "has_attachment": False,
}
SCENARIO = {
    "goal": "Welche Mails gab es diese Woche ?",
    "clock_at": "2026-10-20T12:00:00+00:00",
    "schemas": {"search_emails": SCHEMA},
    "expected_query_arguments": ARGS,
    "query_payload": {
        "messages": [
            {
                "subject": "Observed synthetic message",
                "sender": "Synthetic Sender",
                "received": "2026-10-19T10:00:00+02:00",
                "uid": 1,
                "message_id": "synthetic-one",
                "folder": "INBOX",
            }
        ]
    },
}
pinned_case = pytest.mark.parametrize("read_mailbox", [SCENARIO], indirect=True)


@pytest.fixture
def overview(read_mailbox, monkeypatch):
    app, _, _, cfg, identifier, _, _ = read_mailbox
    with app.state.sessions() as db:
        profile = db.get(Integration, identifier)
        object.__setattr__(cfg, "proton_bridge_integration_id", identifier)
        object.__setattr__(cfg, "proton_bridge_mcp_url", json.loads(profile.config)["url"])
    no_research(monkeypatch)

    async def no_model(*args):
        pytest.fail("Pinned plain mail overview must not need a local/cloud model decision")

    monkeypatch.setattr(runtime, "generate", no_model)
    return read_mailbox


def query_calls(case):
    return [c for c in case[-1] if c["method"] == "tools/call"]


def catalog_and_plan(case):
    """Prepare a synthetic observed catalog and durable intent, without transport."""
    app, _, _, cfg, identifier, job_id, _ = case
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        profiles = runtime.gate(db, cfg, job)
        runtime.prepare_mail_catalogs(db, job, profiles)
        catalog = runtime.steps(db, job_id)[0]
        catalog.status = "succeeded"
        catalog.result = runtime.encode(
            {"tools": [{"name": "search_emails", "input_schema": SCHEMA}]}
        )
        assert runtime.prepare_mail_overview(db, cfg, job, profiles, runtime.steps(db, job_id))
        planned = runtime.steps(db, job_id)[-1]
        assert json.loads(planned.document)["source"] == "application_mail_overview"
        db.commit()
        return planned.sequence


@pinned_case
def test_pinned_week_overview_is_schema_bound_durable_real_read_without_model(
    overview, monkeypatch
):
    app, client, _, cfg, identifier, job_id, _ = overview
    original = runtime.dispatch
    observed_intents = []

    def dispatch(factory, settings, current_job, sequence):
        with factory() as db:
            row = db.get(AgentJob, current_job)
            step = runtime.steps(db, current_job)[-1]
            document = json.loads(step.document)
            if document.get("source") == "application_mail_overview":
                assert step.status == "prepared" and runtime.digest(step.document) == step.sha256
                assert document["planner"] == "schema_bound_calendar_read_v1"
                assert document["arguments"]["arguments"] == ARGS
                binding = json.loads(row.bindings)
                assert document["calendar_plan"] == {
                    "window": "week",
                    "frozen_clock_sha256": runtime.digest(runtime.encode(binding["clock"])),
                    "prefilter_start_date": "2026-10-18",
                    "since_days": 2,
                }
                assert (
                    document["target"]["profile_revision"]
                    == binding["profiles"][0]["profile_revision"]
                )
                assert (
                    document["target"]["policy_revision"]
                    == binding["profiles"][0]["policy_revision"]
                )
                observed_intents.append(document)
        original(factory, settings, current_job, sequence)

    monkeypatch.setattr(runtime, "dispatch", dispatch)
    status, history = execute(overview)
    assert status == "observed" and len(observed_intents) == 1
    assert not any(s.kind in {"model", "effect", "research"} for s in history)
    assert (
        len(query_calls(overview)) == 1 and query_calls(overview)[0]["params"]["arguments"] == ARGS
    )
    response = client.get("/api/agent-runs/" + job_id).json()
    assert (
        "Observed synthetic message" in response["summary"]
        and "keine Vollständigkeit" in response["summary"]
    )
    assert response["automatic_retry"] is False
    before = len(overview[-1])
    execute(overview)
    assert len(overview[-1]) == before  # Terminal worker reentry never repeats the read.


@pytest.mark.parametrize(
    "read_mailbox",
    [
        {
            **SCENARIO,
            "goal": goal,
            "expected_query_arguments": {**ARGS, "since_days": since_days},
            "query_payload": {
                "messages": [
                    {
                        **SCENARIO["query_payload"]["messages"][0],
                        "received": "2026-10-20T10:00:00+02:00",
                    }
                ]
            },
        }
        for goal, since_days in (
            ("Was gab es heute für neue Mails?", 1),
            ("Welche Mails sind heute eingegangen?", 1),
            ("Zeig mir meine neuen Mails von heute", 1),
            ("Was gab es diese Woche für neue Mails?", 2),
        )
    ],
    indirect=True,
)
def test_natural_arrival_questions_query_once_without_confirmation_or_folder_question(overview):
    _, client, _, _, _, job_id, _ = overview
    status, history = execute(overview)
    assert status == "observed" and len(query_calls(overview)) == 1
    assert not any(s.kind in {"input", "model", "effect", "research"} for s in history)
    response = client.get("/api/agent-runs/" + job_id).json()
    assert "Observed synthetic message" in response["summary"]
    assert "INBOX" in response["summary"] and "keine Vollständigkeit" in response["summary"]
    before = len(overview[-1])
    execute(overview)
    assert len(overview[-1]) == before


@pinned_case
@pytest.mark.parametrize("change", ["policy", "profile", "cancel"])
def test_revocation_or_cancel_after_intent_before_dispatch_prevents_mail_read(
    overview, monkeypatch, change
):
    app, _, _, _, identifier, job_id, _ = overview
    original = runtime.dispatch

    def dispatch(factory, cfg, current_job, sequence):
        with factory() as db:
            step = runtime.steps(db, current_job)[-1]
            if json.loads(step.document).get("source") == "application_mail_overview":
                if change == "policy":
                    row = db.get(AgentPolicy, identifier)
                    row.revision += 1
                elif change == "profile":
                    row = db.get(Integration, identifier)
                    row.revision += 1
                else:
                    db.get(AgentJob, job_id).cancel_requested = True
                db.commit()
        original(factory, cfg, current_job, sequence)

    monkeypatch.setattr(runtime, "dispatch", dispatch)
    status, history = execute(overview)
    assert status == ("cancelled" if change == "cancel" else "failed")
    assert not query_calls(overview) and not any(s.kind == "model" for s in history)


@pinned_case
def test_fresh_schema_change_at_final_transport_boundary_blocks_query(overview, monkeypatch):
    original = runtime.dispatch

    def dispatch(factory, cfg, current_job, sequence):
        with factory() as db:
            document = json.loads(runtime.steps(db, current_job)[-1].document)
        if document.get("source") == "application_mail_overview":
            monkeypatch.setitem(
                SCENARIO["schemas"],
                "search_emails",
                {**SCHEMA, "description": "Changed after planning"},
            )
        original(factory, cfg, current_job, sequence)

    monkeypatch.setattr(runtime, "dispatch", dispatch)
    status, history = execute(overview)
    assert status == "uncertain" and not query_calls(overview)
    assert not any(s.kind == "model" for s in history)


@pinned_case
def test_prepared_intent_resumes_once_without_duplicate_plan(overview):
    catalog_and_plan(overview)
    status, history = execute(overview)
    assert status == "observed" and len(query_calls(overview)) == 1
    assert (
        sum(json.loads(s.document).get("source") == "application_mail_overview" for s in history)
        == 1
    )


@pinned_case
@pytest.mark.parametrize("interrupted", ["dispatching", "uncertain", "failed"])
def test_interrupted_or_ambiguous_read_is_never_replayed(overview, interrupted):
    app, _, _, _, _, job_id, _ = overview
    sequence = catalog_and_plan(overview)
    with app.state.sessions() as db:
        runtime.steps(db, job_id)[-1].status = interrupted
        db.commit()
    status, history = execute(overview)
    assert status == "uncertain" and not query_calls(overview)
    assert next(s for s in history if s.sequence == sequence).status in {"uncertain", "failed"}


@pinned_case
def test_tampered_prepared_intent_is_rejected_without_replanning(overview):
    app, _, _, _, _, job_id, _ = overview
    catalog_and_plan(overview)
    with app.state.sessions() as db:
        step = runtime.steps(db, job_id)[-1]
        document = json.loads(step.document)
        document["arguments"]["arguments"]["since_days"] = 0
        step.document = runtime.encode(document)  # Deliberately leave pinned intent hash unchanged.
        db.commit()
    status, _ = execute(overview)
    assert status == "failed" and not query_calls(overview)


@pinned_case
@pytest.mark.parametrize(
    "unsupported",
    ["unknown_required", "missing_folder_default", "invalid_limit", "requires_unread"],
)
def test_schema_with_unsupported_arguments_does_not_guess_or_query(overview, unsupported):
    app, _, _, _, identifier, _, _ = overview
    changed = {
        **SCHEMA,
        "properties": {**SCHEMA["properties"], "account_selector": {"type": "string"}},
        "required": ["account_selector"],
    }
    if unsupported != "unknown_required":
        changed = {**SCHEMA, "properties": dict(SCHEMA["properties"])}
        if unsupported == "missing_folder_default":
            changed["properties"]["folder"] = {"type": "string"}
        elif unsupported == "invalid_limit":
            changed["properties"]["limit"] = {"type": "integer", "maximum": 5}
        else:
            changed["properties"]["unread_only"] = {"const": True}
    with app.state.sessions() as db:
        policy = db.get(AgentPolicy, identifier)
        rules = json.loads(policy.rules)
        rules["mcp_read_tools"] = {"search_emails": schema_digest(changed)}
        policy.rules = json.dumps(rules)
        db.commit()
    # Bindings still refer to the same reviewed revision; this synthetic test
    # changes only the declared contract and exercises the unsupported-shape guard.
    SCENARIO["schemas"]["search_emails"] = changed
    try:
        status, history = execute(overview)
    finally:
        SCENARIO["schemas"]["search_emails"] = SCHEMA
    assert status == "unverified" and not query_calls(overview)
    assert not any(s.kind == "model" for s in history)


@pinned_case
def test_failed_mail_read_is_terminal_and_never_replayed(overview, monkeypatch):
    original = runtime.invoke
    attempts = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        if tool == "mcp.call":
            before_send()
            attempts.append(tool)
            raise TimeoutError("Synthetic response lost")
        return original(cfg, config, secret, tool, args, rules, before_send)

    monkeypatch.setattr(runtime, "invoke", invoke)
    status, history = execute(overview)
    assert status == "uncertain" and attempts == ["mcp.call"]
    assert not any(s.kind == "model" for s in history)
    execute(overview)
    assert attempts == ["mcp.call"]


@pinned_case
@pytest.mark.parametrize(
    "reason", [
        "timeout", "remote_tool_error", "response_limit", "schema_changed", "protocol_error",
        "schema_startup_timeout", "schema_validation_timeout", "schema_invalid_schema",
        "schema_resource_limit",
    ]
)
def test_mail_read_failure_keeps_safe_category_without_replaying_intent(
    overview, monkeypatch, reason
):
    from hub.agent_schema import SchemaValidationFailure
    from hub.mcp_client import MCPFailure

    original = runtime.invoke
    attempts = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        if tool == "mcp.call":
            before_send()
            attempts.append(tool)
            error = (
                SchemaValidationFailure(reason.removeprefix("schema_"))
                if reason.startswith("schema_") and reason != "schema_changed"
                else MCPFailure(reason)
            )
            raise error from ValueError("private.example/secret-mail-body")
        return original(cfg, config, secret, tool, args, rules, before_send)

    monkeypatch.setattr(runtime, "invoke", invoke)
    status, history = execute(overview)
    assert status == "uncertain" and attempts == ["mcp.call"]
    failed = next(s for s in history if s.kind == "read" and s.status == "failed")
    receipt = json.loads(failed.result)
    expected = reason
    if reason.startswith("schema_") and reason != "schema_changed":
        expected = "timeout" if reason.endswith("_timeout") else "protocol_error"
        assert receipt["failure_phase"] == reason
    assert receipt["failure_category"] == expected and receipt["automatic_retry"] is False
    app, client, _, cfg, _, job_id, _ = overview
    assert "private.example" not in client.get("/api/agent-runs/" + job_id).text
    # Direct reentry is blocked too, independently of the terminal job loop.
    runtime.dispatch(app.state.sessions, cfg, job_id, failed.sequence)
    execute(overview)
    assert attempts == ["mcp.call"]


@pinned_case
@pytest.mark.parametrize("unsupported", ["analysis", "wrong_pin", "native", "multiple", "context"])
def test_other_goals_accounts_and_native_mail_remain_outside_automatic_preparation(
    overview, unsupported
):
    app, _, _, cfg, identifier, job_id, _ = overview
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        profiles = runtime.gate(db, cfg, job)
        if unsupported == "analysis":
            job.goal = "Fasse die Inhalte meiner Mails diese Woche zusammen"
        elif unsupported == "wrong_pin":
            object.__setattr__(cfg, "proton_bridge_integration_id", "different")
        elif unsupported == "native":
            profiles[identifier][0].kind = "gmail"
        elif unsupported == "context":
            job.context = json.dumps([{"content": "Use only the synthetic Archive folder"}])
        else:
            profiles["second"] = profiles[identifier]
        assert not runtime.prepare_mail_overview(db, cfg, job, profiles, [])


@pytest.mark.parametrize(
    "read_mailbox",
    [
        {
            **SCENARIO,
            "goal": "Welche neuen Mails gab es heute?",
            "schemas": {
                "list_emails": {
                    **SCHEMA,
                    "properties": {
                        k: v
                        for k, v in SCHEMA["properties"].items()
                        if k not in {"query", "has_attachment"}
                    },
                }
            },
            "expected_query_tool": "list_emails",
            "expected_query_arguments": {
                k: (1 if k == "since_days" else v)
                for k, v in ARGS.items()
                if k not in {"query", "has_attachment"}
            },
        }
    ],
    indirect=True,
)
def test_today_uses_observed_list_schema_when_no_search_tool_is_granted(overview):
    status, history = execute(overview)
    assert status == "observed" and len(query_calls(overview)) == 1
    call = query_calls(overview)[0]["params"]
    assert call["name"] == "list_emails" and call["arguments"]["since_days"] == 1
    planned = next(
        json.loads(s.document)
        for s in history
        if json.loads(s.document).get("source") == "application_mail_overview"
    )
    assert planned["calendar_plan"]["window"] == "today"
    assert planned["calendar_plan"]["prefilter_start_date"] == "2026-10-19"
    assert not any(s.kind == "model" for s in history)
