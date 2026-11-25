"""Two-turn, source-bound empty display; absence of references is never zero mail."""
# Imported shared pytest fixtures intentionally share argument names.
# ruff: noqa: F811
import json

import pytest
from hub import agent_mail_cohort as cohort
from hub import agent_mail_reply_summary as summary
from hub import agent_read_references as refs
from hub.action_api import encode
from hub.agent_models import AgentStep
from hub.db import Message
from sqlalchemy import func, select
from test_agent_mail_cohort import context, freeze, row  # noqa: F401
from test_agent_read_references import receipt  # noqa: F401

GOAL = "Auf welche dieser Mails habe ich bereits geantwortet?"


def empty_first_turn(context):
    # Six genuine synthetic receipts were returned but NONE belonged to today's display.
    freeze(context, [row(i, received="2026-10-20T09:00:00+02:00") for i in range(1, 7)])
    context[1].goal = GOAL
    context[0].flush()
    return context


def test_two_turn_outside_window_is_known_empty_not_missing_reference(context):
    db, job, source, message, _, _, _, profiles = empty_first_turn(context)
    selected = cohort.selected_receipt_rows(db, job, profiles)
    assert selected["cohort_known"] is True and selected["rows"] == []
    assert selected["source_receipts"] and source.summary == message.content
    before = db.scalar(select(func.count()).select_from(AgentStep))
    text = summary.empty_mail_reply_summary(db, job, profiles)
    assert text and "Auswahl für den angefragten Zeitraum waren 0 Mails" in text
    assert "keine Aussage" in text and "Gesendet-Ordner wurde dafür nicht geprüft" in text
    assert "Synthetic" not in text
    assert summary.mail_reply_summary(db, job, profiles, []) == text
    assert db.scalar(select(func.count()).select_from(AgentStep)) == before
    assert not db.dirty


@pytest.mark.parametrize("goal", [
    "Welche davon habe ich beantwortet?", "Were any of those replied to?",
    "Which of the previously listed messages have I already replied to?",
    "Antwortstatus der angezeigten Mails",
])
def test_explicit_display_reference_language_variants(context, goal):
    db, job, _, _, _, _, _, profiles = empty_first_turn(context)
    job.goal = goal
    assert summary.empty_mail_reply_summary(db, job, profiles) is not None


@pytest.mark.parametrize("goal", [
    "Auf welche Mails habe ich bereits geantwortet?",
    "Welche Mails habe ich beantwortet und lösche sie?",
    "Welche dieser Mails habe ich heute beantwortet?",
    "Welche dieser Mails von Alice habe ich beantwortet?",
])
def test_unscoped_or_unhandled_filter_or_compound_is_not_completed(context, goal):
    db, job, _, _, _, _, _, profiles = empty_first_turn(context)
    job.goal = goal
    assert summary.empty_mail_reply_summary(db, job, profiles) is None


@pytest.mark.parametrize("case", ["missing_refs", "ordinary_latest", "changed_summary", "gmail"])
def test_unknown_or_unsupported_is_not_empty(context, case):
    db, job, source, message, _, profile, _, profiles = empty_first_turn(context)
    if case == "missing_refs":
        job.context = "[]"
    elif case == "ordinary_latest":
        other = Message(conversation_id=job.conversation_id, role="assistant",
                        content="Synthetic unrelated ordinary answer", created=message.created + 1)
        db.add(other)
        job.created = message.created + 2
        db.flush()
        job.context = encode(refs.bind(db, job, [message, other], profiles))
        assert json.loads(job.context) == []
    elif case == "changed_summary":
        source.summary = "Synthetic changed source summary"
    else:
        profile.kind = "gmail"
    assert summary.empty_mail_reply_summary(db, job, profiles) is None
    if case == "gmail":
        with pytest.raises(PermissionError):
            summary.mail_reply_summary(db, job, profiles, [])
    else:
        assert summary.mail_reply_summary(db, job, profiles, []) is None


@pytest.mark.parametrize("case", ["revoked", "edited_receipt", "edited_message"])
def test_current_receipt_revocation_still_fails_closed(context, case):
    db, job, _, message, step, profile, _, profiles = empty_first_turn(context)
    if case == "revoked":
        profile.enabled = False
    elif case == "edited_receipt":
        step.result += " "
    else:
        message.revision += 1
    with pytest.raises(PermissionError):
        summary.empty_mail_reply_summary(db, job, profiles)


def test_real_empty_payload_is_known_but_nonempty_or_unknown_dates_are_not(context):
    db, job, _, _, _, _, _, profiles = context
    job.goal = GOAL
    freeze(context, [])
    assert summary.empty_mail_reply_summary(db, job, profiles) is not None
    freeze(context, [row(1)])
    assert summary.empty_mail_reply_summary(db, job, profiles) is None
    freeze(context, [row(2, received="unknown")])
    assert summary.empty_mail_reply_summary(db, job, profiles) is None
