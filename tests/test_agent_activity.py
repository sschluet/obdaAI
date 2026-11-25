"""Visible work feedback is based on receipts, not model prose or fake completion."""

import json
from types import SimpleNamespace

import pytest
from hub.agent_activity import activity


def job(status="running", **overrides):
    return SimpleNamespace(id="synthetic-job", status=status, created=100.0, finished=None,
                           cancel_requested=False, **overrides)


def step(kind="model", status="dispatching", sequence=1, document=None):
    return SimpleNamespace(kind=kind, status=status, sequence=sequence, created=110.0,
                           document=json.dumps(document or {}))


def test_queued_job_does_not_pretend_model_or_target_execution_started():
    value = activity(job("queued"), [], now=120)
    assert value["phase"] == "queued" and value["can_cancel"]
    assert value["completed_steps"] == value["total_steps"] == 0
    assert value["updated_at"] == 100 and value["elapsed_seconds"] == 20


def test_model_queue_and_inference_are_visible_without_reasoning_or_tool_claims():
    item = step(document={"intent_interpretation": True, "reasoning": "PRIVATE_REASONING"})
    run = SimpleNamespace(status="queued", finished=None)
    queued = activity(job(), [item], model_run=run, now=120)
    assert queued["phase"] == "planning" and "zuordnen" in queued["message"]
    assert "Wartet" in queued["waiting_reason"]
    run.status = "streaming"
    running = activity(job(), [item], model_run=run, now=121)
    assert "verarbeitet" in running["waiting_reason"]
    assert queued["event_key"] != running["event_key"]
    assert "PRIVATE_REASONING" not in json.dumps(running)


@pytest.mark.parametrize("kind,phase", [
    ("read", "reading"), ("research", "researching"), ("effect", "changing"),
    ("verification", "verifying"), ("feedback", "recovering"),
])
def test_active_operation_uses_actual_kind_never_model_written_message(kind, phase):
    value = activity(job(), [step(kind, document={
        "message": "Everything is complete!", "arguments": {"password": "PRIVATE_SECRET"},
    })], now=120)
    assert value["phase"] == phase and value["can_cancel"]
    assert "PRIVATE_SECRET" not in json.dumps(value)
    assert "Everything is complete!" not in json.dumps(value)


def test_prepared_change_is_not_described_as_already_executing():
    value = activity(job(), [step("effect", "prepared")], now=120)
    assert value["message"] == "Änderung vorbereiten"


@pytest.mark.parametrize("status,phase", [
    ("awaiting_approval", "approval"), ("awaiting_input", "input"),
    ("uncertain", "uncertain"), ("unverified", "uncertain"),
])
def test_attention_states_explain_next_action_without_automatic_retry(status, phase):
    value = activity(job(status), [step("effect", "prepared")], now=120)
    assert value["phase"] == phase and value["next_action"]
    if phase == "uncertain":
        assert not value["can_cancel"] and "nicht erneut" in value["next_action"]


def test_failure_after_effect_never_invites_repeating_whole_request():
    read = activity(job("failed"), [step("read", "failed")], now=120)
    effect = activity(job("failed"), [step("effect", "failed")], now=120)
    assert "erneut vorbereitet" in read["next_action"]
    assert "Prüfe die bisherigen Änderungen" in effect["next_action"]
    assert "erneut vorbereitet" not in effect["next_action"]


def test_recorded_counts_are_not_percentages_or_predictions_of_remaining_work():
    items = [step("model", "succeeded", 1), step("read", "succeeded", 2),
             step("feedback", "prepared", 3), step("read", "failed", 4)]
    value = activity(job("observed"), items, now=120)
    assert value["completed_steps"] == 1 and value["total_steps"] == 2
    assert value["message"] == "Abfrage abgeschlossen"
    assert "percent" not in value and "remaining_steps" not in value


def test_terminal_elapsed_stops_and_timeline_is_bounded_without_model_steps():
    owner = job("succeeded")
    owner.finished = 125.0
    items = [step("read", "succeeded", n) for n in range(1, 10)]
    value = activity(owner, items, now=900)
    assert value["elapsed_seconds"] == 25 and value["updated_at"] == 125
    assert len(value["timeline"]) == 6 and value["timeline"][0]["sequence"] == 4


def test_cancellation_is_pending_not_a_claim_remote_processes_were_stopped():
    owner = job()
    owner.cancel_requested = True
    value = activity(owner, [step("effect")], now=120)
    assert value["message"] == "Abbruch angefordert" and not value["can_cancel"]
    assert "abgeglichen" in value["waiting_reason"]
