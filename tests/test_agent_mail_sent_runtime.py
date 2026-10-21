"""Whole-cohort answer readiness requires the actual Sent read, without new rights."""

import copy

import pytest
from hub.agent_runtime import mail_read_plan
from hub.agent_schema import validate
from hub.agent_tools import ready_read_schema
from test_agent_mail_cohort import context as cohort_context  # noqa: F401
from test_agent_mail_cohort import current, row
from test_agent_mail_sent_progress import (
    contracts,
    folders,
    sent_context,  # noqa: F401
    step,
)
from test_agent_read_references import receipt  # noqa: F401


def plan(fixture, history):
    ctx, _ = fixture
    ctx[1].goal = "Welche davon habe ich bereits beantwortet?"
    return mail_read_plan(ctx[0], ctx[1], ctx[-1], history, contracts(fixture))


def test_detail_then_observed_folder_then_sent_query_before_whole_cohort_answer(sent_context):  # noqa: F811
    ctx, _ = sent_context
    detail = current(ctx, "read_email", row(1, answered=True))
    first = plan(sent_context, [detail])
    assert first["has_data"] and not first["allow_finish"]
    assert first["ready"]["decisions"][0]["arguments"]["name"] == "list_folders"
    assert first["reply_evidence"] == {"sent_query_required": True, "cohort_known": True}
    discovered = folders(sent_context)
    discovered.sequence = 2
    second = plan(sent_context, [detail, discovered])
    assert not second["allow_finish"]
    candidate = second["ready"]["decisions"][0]
    assert candidate["arguments"]["arguments"] == {"folder": "Actual Sent", "limit": 20}
    queried = step(
        sent_context, "list_emails", {"folder": "Actual Sent", "messages": []}, sequence=3,
        args={"folder": "Actual Sent", "limit": 20},
    )
    last = plan(sent_context, [detail, discovered, queried])
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
    result = plan(sent_context, [detail, discovered])
    assert not result["allow_finish"] and not result["ready"]["decisions"]
    assert result["reply_evidence"]["sent_query_observed"] is False
    assert result["reply_evidence"]["displayed_count"] == 2


def test_native_sent_choices_cannot_finish_or_change_observed_folder(sent_context):  # noqa: F811
    ctx, _ = sent_context
    discovered = folders(sent_context)
    discovered.sequence = 2
    result = plan(sent_context, [current(ctx, "read_email", row(1)), discovered])
    candidate = result["ready"]["decisions"][0]
    identifier = ctx[5].id
    schema = ready_read_schema([candidate], [{
        "integration_id": identifier, "kind": "mcp", "rules": ctx[-1][identifier][1].model_dump(),
    }])
    validate(schema, candidate)
    changed = copy.deepcopy(candidate)
    changed["arguments"]["arguments"]["folder"] = "Unobserved mailbox"
    with pytest.raises(ValueError):
        validate(schema, changed)
    with pytest.raises(ValueError):
        validate(schema, {"kind": "finish", "message": "Skip Sent check"})
