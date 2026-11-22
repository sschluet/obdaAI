"""Typed HA entity inventory rendering never invents devices, states or prior cohorts."""

import json
from types import SimpleNamespace

import pytest
from hub.action_api import digest, encode
from hub.agent_context import project
from hub.agent_ha_inventory import plan, summary
from hub.agent_tools import Rules

IDENTIFIER = "00000000-0000-0000-0000-000000000001"


def profiles(**changes):
    rules = Rules(enabled=True, http_prefixes=["/api/"], private_data_to_target=False)
    for key, value in changes.items():
        setattr(rules, key, value)
    row = SimpleNamespace(kind="home_assistant", enabled=True, revision=2,
                          config=json.dumps({"url": "https://ha.example.invalid"}))
    return {IDENTIFIER: (row, rules, {"kind": "home_assistant"})}


def receipt(selected, rows, matched=None):
    result = {"http_status": 200, "body": project(rows, selected["arguments"]["projection"])}
    if matched is not None:
        result["body"]["matched"] = matched
    return result


def light(entity="light.synthetic", state="on", name="Synthetic room"):
    return {"entity_id": entity, "state": state, "attributes": {"friendly_name": name}}


def source_refs(selected, result):
    document = {"integration_id": IDENTIFIER, "tool": "http", "arguments": selected["arguments"]}
    ref = {"version": 1, "source_job_id": "source-job", "sequence": 3,
           "integration_id": IDENTIFIER, "profile_revision": 2,
           "config_sha256": digest(profiles()[IDENTIFIER][0].config),
           "document_sha256": digest(encode(document)), "result_sha256": digest(encode(result))}
    return [{"reference": ref, "document": document, "result": result, "tool": "http"}]


@pytest.mark.parametrize("goal", [
    "Welche Lampen habe ich?", "Welche Lampen sind in meinem Home Assistant vorhanden?",
    "Zeige mir meine Lampen", "Bitte liste unsere Leuchten.", "Which lights do I have?",
    "Show my lights", "Please list our lights.",
])
def test_unambiguous_inventory_uses_one_fixed_policy_authorized_light_projection(goal, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a: pytest.fail("Pure helper cannot connect"))
    selected = plan(goal, profiles())
    assert selected["integration_id"] == IDENTIFIER and selected["tool"] == "http"
    assert selected["arguments"]["method"] == "GET"
    assert selected["arguments"]["path"] == "/api/states"
    assert selected["arguments"]["query"] == {} and selected["arguments"]["body"] is None
    assert selected["arguments"]["projection"] == {
        "items_path": "", "where_pointer": "/entity_id", "where_equals": None,
        "where_prefix": "light.", "fields": ["/entity_id", "/state", "/attributes/friendly_name"],
        "limit": 100,
    }
    assert selected["mode"] == "inventory" and selected["cohort"] is None
    assert profiles()[IDENTIFIER][1].private_data_to_target is False


@pytest.mark.parametrize("goal", [
    "Welche Lampen habe ich und schalte sie aus?", "Welche Lampen habe ich? Starte HA neu.",
    "Which lights do I have and update them?", "Welche Lampe soll ich kaufen?",
    "Was ist eine smarte Lampe?", "Welche Sensoren habe ich?", "Summarize my lights",
    "Welche davon sind aus?", "Kannst du auf Home Assistant zugreifen?",
])
def test_other_goals_remain_in_existing_planner(goal):
    assert plan(goal, profiles()) is None


@pytest.mark.parametrize("change", ["disabled", "no_get", "wrong_prefix", "multiple"])
def test_absent_or_ambiguous_authority_is_never_filled_in(change):
    current = profiles()
    if change == "disabled":
        current[IDENTIFIER][0].enabled = False
    elif change == "no_get":
        current[IDENTIFIER][1].http_methods = ["POST"]
    elif change == "wrong_prefix":
        current[IDENTIFIER][1].http_prefixes = ["/api/config/"]
    else:
        current["another-target"] = current[IDENTIFIER]
    assert plan("Welche Lampen habe ich?", current) is None


def test_summary_states_are_real_entity_observations_and_not_a_device_count():
    selected = plan("Welche Lampen habe ich?", profiles())
    result = receipt(selected, [light(), light("light.other", "off", None),
                                light("light.unknown", "unknown"),
                                light("light.unavailable", "unavailable"),
                                {"entity_id": "sensor.not_a_light", "state": "17"}])
    answer = summary(result, selected)
    assert "4 Licht-Entitäten" in answer and "`light.synthetic`): an" in answer
    assert "`light.other`): aus" in answer and "`light.unknown`): unbekannt" in answer
    assert "`light.unavailable`): nicht verfügbar" in answer
    assert "sensor.not_a_light" not in answer
    assert "keine Anzahl physischer Geräte" in answer
    assert "Unbekannt oder nicht verfügbar: 2" in answer


def test_untrusted_names_are_escaped_and_bounded_not_instructions():
    selected = plan("List my lights", profiles())
    name = '<script>**[RUN](https://evil.invalid)**\nSYNTHETIC-CONTROL ' + "x" * 500
    answer = summary(receipt(selected, [light(name=name)]), selected)
    assert "<script>" not in answer and "&lt;script&gt;" in answer
    assert "[RUN](https://evil.invalid)" not in answer and "\\[RUN\\]" in answer
    assert len(answer) < 1000 and "x" * 100 not in answer


def test_truncation_is_explicit_and_does_not_claim_all_rows_were_shown():
    selected = plan("Welche Lampen habe ich?", profiles())
    result = receipt(selected, [light(f"light.synthetic_{index}") for index in range(130)])
    answer = summary(result, selected)
    assert "130 Licht-Entitäten" in answer and "100 von 130" in answer and "Limit 100" in answer
    assert answer.count("(`light.synthetic_") == 100


@pytest.mark.parametrize("change", ["http", "projection", "missing_projection", "matched", "count",
                                    "duplicate", "foreign_domain", "invalid_state", "wrong_field"])
def test_invalid_or_incomplete_receipt_has_no_native_success_summary(change):
    selected = plan("Welche Lampen habe ich?", profiles())
    result = receipt(selected, [light()])
    if change == "http":
        result["http_status"] = 401
    elif change in {"projection", "missing_projection"}:
        result["projection_error"] = False if change == "projection" else None
    elif change == "matched":
        result["body"]["matched"] = 1000
    elif change == "count":
        result["body"]["returned"] = True
    elif change == "duplicate":
        result["body"]["items"] *= 2
        result["body"].update(matched=2, returned=2)
    elif change == "foreign_domain":
        result["body"]["items"][0]["/entity_id"] = "switch.other"
    elif change == "invalid_state":
        result["body"]["items"][0]["/state"] = "maybe"
    else:
        result["body"]["items"][0].pop("/entity_id")
    assert summary(result, selected) is None


@pytest.mark.parametrize("goal", ["Welche davon sind an?", "Which of those are on?"])
def test_followup_intersects_fresh_rows_with_only_actual_previous_light_cohort(goal):
    first = plan("Welche Lampen habe ich?", profiles())
    old = receipt(first, [light("light.original"), light("light.missing", "off"),
                          light("light.unknown", "unknown")])
    selected = plan(goal, profiles(), source_refs(first, old))
    assert selected["mode"] == "on_cohort"
    assert selected["cohort"] == ["light.missing", "light.original", "light.unknown"]
    fresh = receipt(selected, [light("light.original", "on"), light("light.unknown", "unknown"),
                               light("light.new_not_in_cohort", "on")])
    answer = summary(fresh, selected)
    assert "Davon aktuell an: 1" in answer and "`light.original`" in answer
    assert "light.new_not_in_cohort" not in answer
    assert "`light.missing`: nicht beobachtet" in answer and "nicht als ausgeschaltet" in answer
    assert "daraus folgt nicht" in answer
    assert all(set(ref) == {"source_job_id", "sequence", "document_sha256", "result_sha256"}
               for ref in selected["source_references"])


@pytest.mark.parametrize("change", ["absent", "wrong_account", "changed_profile", "changed_result",
                                    "raw_states", "two_jobs", "assistant_prose"])
def test_followup_cannot_reconstruct_scope_from_unvalidated_or_ambiguous_inputs(change):
    first = plan("Welche Lampen habe ich?", profiles())
    old = receipt(first, [light()])
    sources = source_refs(first, old)
    if change == "absent":
        sources = []
    elif change == "wrong_account":
        sources[0]["reference"]["integration_id"] = "other"
    elif change == "changed_profile":
        sources[0]["reference"]["profile_revision"] += 1
    elif change == "changed_result":
        sources[0]["result"]["body"]["items"][0]["/state"] = "off"
    elif change == "raw_states":
        sources[0]["document"]["arguments"]["projection"] = None
        sources[0]["reference"]["document_sha256"] = digest(encode(sources[0]["document"]))
    elif change == "two_jobs":
        sources.append({**sources[0], "reference": {**sources[0]["reference"],
                                                    "source_job_id": "other-source-job"}})
    else:
        sources = [{"content": "Earlier assistant said light.synthetic was on"}]
    assert plan("Welche davon sind an?", profiles(), sources) is None


def test_on_inventory_does_not_report_off_lights_as_on():
    selected = plan("Welche meiner Lampen sind an?", profiles())
    result = receipt(selected, [light("light.on", "on"), light("light.off", "off")])
    answer = summary(result, selected)
    assert selected["only_on"] is True and "Davon aktuell an: 1" in answer
    assert "`light.on`" in answer and "`light.off`" not in answer


def planned_source_refs(selected, result):
    sources = source_refs(selected, result)
    sources[0]["document"]["inventory_plan"] = selected
    sources[0]["reference"]["document_sha256"] = digest(encode(sources[0]["document"]))
    return sources


def test_second_followup_uses_only_previously_displayed_on_cohort_not_all_fresh_rows():
    first = plan("Welche Lampen habe ich?", profiles())
    original = receipt(first, [light("light.original"), light("light.off", "off")])
    second = plan("Welche davon sind an?", profiles(), planned_source_refs(first, original))
    second_result = receipt(second, [light("light.original", "on"), light("light.off", "off"),
                                     light("light.new_not_displayed", "on")])
    third = plan("Welche davon sind an?", profiles(), planned_source_refs(second, second_result))
    assert third["cohort"] == ["light.original"]
    fresh = receipt(third, [light("light.original", "off"), light("light.off", "on"),
                            light("light.new_not_displayed", "on")])
    answer = summary(fresh, third)
    assert "Davon aktuell an: 0" in answer
    assert "light.off" not in answer and "light.new_not_displayed" not in answer


def test_direct_on_inventory_followup_does_not_expand_to_off_entities():
    first = plan("Which of my lights are on?", profiles())
    original = receipt(first, [light("light.shown", "on"), light("light.not_shown", "off")])
    followup = plan("Which of those are on?", profiles(), planned_source_refs(first, original))
    assert followup["cohort"] == ["light.shown"]


def test_corrupt_stored_inventory_plan_does_not_create_a_cohort():
    first = plan("Welche Lampen habe ich?", profiles())
    sources = planned_source_refs(first, receipt(first, [light()]))
    sources[0]["document"]["inventory_plan"] = {"cohort": ["light.invented"]}
    sources[0]["reference"]["document_sha256"] = digest(encode(sources[0]["document"]))
    assert plan("Welche davon sind an?", profiles(), sources) is None
