"""An interrupted administration job keeps useful facts without claiming success."""

import copy
import json
from types import SimpleNamespace

import pytest
from hub.agent_terminal_summary import terminal_summary
from test_agent_ha_evidence import receipt


def owner(requirement=True):
    return SimpleNamespace(bindings=json.dumps({"intent": {"requirements": [
        {"kind": "entity_states", "domain": "update", "integration_id": "ha"},
    ] if requirement else []}}))


def effect(*, verified=False, status="succeeded", sequence=2):
    return SimpleNamespace(kind="effect", status=status, sequence=sequence,
                           document=json.dumps({"integration_id": "ha"}),
                           result=json.dumps({"effect_verified": verified}))


def data(*, sequence=1):
    return receipt([{"entity_id": "update.core", "state": "on", "attributes": {
        "friendly_name": "UNTRUSTED_TARGET_PROSE", "installed_version": "1",
        "latest_version": "2",
    }}], sequence=sequence)


def test_failed_preparation_keeps_original_failure_and_useful_actual_read_result():
    history = [data()]
    before = copy.deepcopy(vars(history[0]))
    text = terminal_summary(owner(), history, "failed", "Planung angehalten.")
    assert text.startswith("Planung angehalten.")
    assert "keine Änderung gestartet" in text
    assert "1 verfügbares Update beobachtet" in text
    assert "UNTRUSTED_TARGET_PROSE" not in text and "installiert" not in text
    assert vars(history[0]) == before


def test_read_result_is_never_selected_by_question_keywords_or_model_final_prose():
    text = terminal_summary(owner(False), [data()], "failed", "Home Assistant Updates?")
    assert "verfügbare Updates" not in text


@pytest.mark.parametrize("status", ["uncertain", "failed", "succeeded"])
def test_unconfirmed_effect_preserves_uncertainty_and_never_reuses_pre_effect_inventory(status):
    text = terminal_summary(owner(), [data(), effect(status=status)],
                            "uncertain", "Wirkung unklar.")
    assert "nicht wiederholen" in text
    assert "verfügbare Updates beobachtet" not in text
    assert "keine Änderung gestartet" not in text


def test_verified_partial_effect_does_not_become_overall_success_and_needs_fresh_read():
    text = terminal_summary(owner(), [data(), effect(verified=True), data(sequence=3)],
                            "unverified", "Auftrag noch nicht vollständig belegt.")
    assert "1 Änderungsschritt ist bestätigt" in text
    assert "noch nicht abgeschlossen" in text
    assert "1 verfügbares Update beobachtet" in text


def test_unknown_is_not_summarized_as_zero_available_updates():
    unknown = receipt([{"entity_id": "update.core", "state": "unavailable"}])
    text = terminal_summary(owner(), [unknown], "failed", "Angehalten.")
    assert "unbekannte Zustände" in text and "0 verfügbare" not in text


@pytest.mark.parametrize("status", ["succeeded", "observed", "awaiting_input"])
def test_normal_answers_and_questions_remain_concise_and_unchanged(status):
    assert terminal_summary(owner(), [data()], status, "Kurze Antwort.") == "Kurze Antwort."
