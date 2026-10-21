"""A reply-status request needs current Sent headers, not an irrelevant full body."""

# Imported pytest fixtures intentionally share their argument names.
# ruff: noqa: F811
import copy
import json

import pytest
from hub import agent_mail_cohort as cohort
from hub import agent_runtime as runtime
from hub.action_api import encode
from hub.agent_runtime import mail_read_plan
from hub.agent_schema import validate
from hub.agent_tools import ready_read_schema
from hub.mcp_client import schema_digest
from test_agent_mail_cohort import context as cohort_context  # noqa: F401
from test_agent_mail_cohort import current, row
from test_agent_mail_sent_progress import (
    contracts,
    folders,
    sent_context,  # noqa: F401
    step,
)
from test_agent_read_references import receipt  # noqa: F401


def plan(sent_context, history=None):
    ctx, schemas = sent_context
    ctx[1].goal = "Welche davon habe ich bereits beantwortet?"
    schema = {
        "type": "object",
        "properties": {"uid": {"type": "integer", "minimum": 1}, "folder": {"type": "string"}},
        "required": ["uid", "folder"],
        "additionalProperties": False,
    }
    schemas["read_email"] = schema
    rules = ctx[-1][ctx[5].id][1]
    rules.mcp_read_tools["read_email"] = schema_digest(schema)
    ctx[6].rules = rules.model_dump_json()
    return runtime.mail_read_plan(ctx[0], ctx[1], ctx[-1], history or [], contracts(sent_context))


def test_known_reply_cohort_starts_with_actual_folder_discovery_no_body(sent_context):
    result = plan(sent_context)
    assert result["has_data"] is False and result["allow_finish"] is False
    assert result["compact_planning"] is True
    assert [d["arguments"]["name"] for d in result["ready"]["decisions"]] == ["list_folders"]


def test_folder_discovery_does_not_finish_and_next_choice_is_sent_headers(sent_context):
    result = plan(sent_context, [folders(sent_context)])
    assert result["has_data"] is False and result["allow_finish"] is False
    assert result["compact_planning"] is True
    decision = result["ready"]["decisions"][0]
    assert decision["arguments"]["name"] == "list_emails"
    assert decision["arguments"]["arguments"] == {"folder": "Actual Sent", "limit": 20}


def test_actual_empty_sent_headers_unlock_qualified_full_cohort_answer(sent_context):
    query = step(
        sent_context,
        "list_emails",
        {"folder": "Actual Sent", "messages": []},
        2,
        {"folder": "Actual Sent", "limit": 20},
    )
    result = plan(sent_context, [folders(sent_context), query])
    assert result["has_data"] is True and result["allow_finish"] is True
    assert result["sent_query_observed"] is True
    facts = result["reply_evidence"]
    assert facts["displayed_count"] == 2 and len(facts["rows"]) == 2
    assert facts["marked_answered_count"] == 1
    assert all(r[3] is None for r in facts["rows"])
    assert facts["false_flag_means_unanswered"] is False
    assert facts["sent_coverage_complete"] is False


def test_unknown_cohort_retains_exact_detail_read_path(sent_context):
    sent_context[0][2].summary = "Not the bound deterministic overview"
    result = plan(sent_context)
    assert result["compact_planning"] is False
    assert [d["arguments"]["name"] for d in result["ready"]["decisions"]] == [
        "read_email",
        "read_email",
    ]
    assert result["allow_finish"] is False


def test_content_question_retains_detail_choice(sent_context):
    ctx, _ = sent_context
    plan(sent_context)  # Observe the synthetic body schema without running a tool.
    ctx[1].goal = "Fasse den Inhalt dieser Mails zusammen"
    result = runtime.mail_read_plan(ctx[0], ctx[1], ctx[-1], [], contracts(sent_context))
    assert result["compact_planning"] is False
    assert result["ready"]["decisions"][0]["arguments"]["name"] == "read_email"


def test_one_current_query_does_not_finish_pending_other_account(sent_context, monkeypatch):
    query = step(
        sent_context, "list_emails", {"messages": []}, 2, {"folder": "Actual Sent", "limit": 20}
    )
    actual = cohort.cohort_evidence

    def pending(*args, **kwargs):
        facts = actual(*args, **kwargs)
        return {**facts, "sent_query_observed": False}

    monkeypatch.setattr(cohort, "cohort_evidence", pending)
    result = plan(sent_context, [folders(sent_context), query])
    assert result["has_data"] is True and result["allow_finish"] is False


def test_missing_sent_after_successful_discovery_allows_stop_not_body_guess(sent_context):
    discovery = step(sent_context, "list_folders", [])
    result = plan(sent_context, [discovery])
    assert result["ready"]["decisions"] == []
    assert result["allow_finish"] is False


def test_sent_planning_compaction_preserves_all_schemas_and_hashes(sent_context):
    plan(sent_context)
    ctx, schemas = sent_context
    tools = [
        {"name": name, "input_schema": schema, "description": "Large prose " * 500}
        for name, schema in schemas.items()
    ]
    catalog = runtime.AgentStep(
        job_id=ctx[1].id,
        sequence=1,
        kind="read",
        status="succeeded",
        document=encode({"integration_id": ctx[5].id, "tool": "mcp.catalog"}),
        result=encode({"tools": tools}),
    )
    full = runtime.mail_read_contracts(ctx[-1], [catalog])
    compact = runtime.mail_read_contracts(ctx[-1], [catalog], include_descriptions=False)
    assert compact["schemas"] == full["schemas"]
    assert [t["schema_sha256"] for t in compact["interfaces"][0]["tools"]] == [
        t["schema_sha256"] for t in full["interfaces"][0]["tools"]
    ]
    assert all("description" not in t for t in compact["interfaces"][0]["tools"])
    assert len(json.dumps(compact)) < len(json.dumps(full))


def old_plan(fixture, history):
    ctx, _ = fixture
    ctx[1].goal = "Welche davon habe ich bereits beantwortet?"
    return mail_read_plan(ctx[0], ctx[1], ctx[-1], history, contracts(fixture))


def test_detail_then_observed_folder_then_sent_query_before_whole_cohort_answer(sent_context):  # noqa: F811
    ctx, _ = sent_context
    detail = current(ctx, "read_email", row(1, answered=True))
    first = old_plan(sent_context, [detail])
    assert first["has_data"] and not first["allow_finish"]
    assert first["ready"]["decisions"][0]["arguments"]["name"] == "list_folders"
    assert first["reply_evidence"] == {"sent_query_required": True, "cohort_known": True}
    discovered = folders(sent_context)
    discovered.sequence = 2
    second = old_plan(sent_context, [detail, discovered])
    assert not second["allow_finish"]
    candidate = second["ready"]["decisions"][0]
    assert candidate["arguments"]["arguments"] == {"folder": "Actual Sent", "limit": 20}
    queried = step(
        sent_context,
        "list_emails",
        {"folder": "Actual Sent", "messages": []},
        sequence=3,
        args={"folder": "Actual Sent", "limit": 20},
    )
    last = old_plan(sent_context, [detail, discovered, queried])
    assert last["allow_finish"] and not last["ready"]
    evidence = last["reply_evidence"]
    assert evidence["sent_query_observed"] and evidence["displayed_count"] == 2
    assert evidence["rows"] == [[1, True, True, None], [2, False, False, None]]
    assert evidence["false_flag_means_unanswered"] is False
    assert evidence["sent_coverage_complete"] is False


def test_missing_sent_capability_allows_only_a_qualified_stop_not_false_completion(
    sent_context,  # noqa: F811
):
    ctx, _ = sent_context
    detail = current(ctx, "read_email", row(1, answered=True))
    discovered = folders(sent_context, flags=[])
    discovered.sequence = 2
    result = old_plan(sent_context, [detail, discovered])
    assert not result["allow_finish"] and not result["ready"]["decisions"]
    assert result["reply_evidence"]["sent_query_observed"] is False
    assert result["reply_evidence"]["displayed_count"] == 2


def test_native_sent_choices_cannot_finish_or_change_observed_folder(sent_context):  # noqa: F811
    ctx, _ = sent_context
    discovered = folders(sent_context)
    discovered.sequence = 2
    result = old_plan(sent_context, [current(ctx, "read_email", row(1)), discovered])
    candidate = result["ready"]["decisions"][0]
    identifier = ctx[5].id
    schema = ready_read_schema(
        [candidate],
        [
            {
                "integration_id": identifier,
                "kind": "mcp",
                "rules": ctx[-1][identifier][1].model_dump(),
            }
        ],
    )
    validate(schema, candidate)
    changed = copy.deepcopy(candidate)
    changed["arguments"]["arguments"]["folder"] = "Unobserved mailbox"
    with pytest.raises(ValueError):
        validate(schema, changed)
    with pytest.raises(ValueError):
        validate(schema, {"kind": "finish", "message": "Skip Sent check"})
