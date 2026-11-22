"""Shared intent contracts, effective schemas and actual goal-specific evidence."""

import json
from types import SimpleNamespace

import pytest
from hub.agent_capabilities import ha_inventory_question
from hub.agent_context import project
from hub.agent_intent import (
    RequestIntent,
    Requirement,
    accept_semantic,
    adequacy,
    infer,
    semantic_request,
    target_budgets,
)
from hub.agent_tools import Rules, decision_schema, effective_interfaces, effective_rules
from hub.integration_routing import relevant
from jsonschema import Draft202012Validator, ValidationError

ID = "11111111-1111-4111-8111-111111111111"


def profiles(kind="home_assistant", **changes):
    row = SimpleNamespace(id=ID, kind=kind, name="Synthetic system", enabled=True)
    rules = Rules(enabled=True, http_prefixes=["/api/"], http_methods=["GET", "POST"], **changes)
    return {ID: (row, rules, {})}


@pytest.mark.parametrize("goal", [
    "Kannst du mir meine Lampen auflisten?", "Welche Lampen sind bei mir vorhanden?",
    "Liste meine Lampen auf", "Welche Lampen habe ich denn?",
    "Wie viele meiner Lampen sind eingeschaltet?",
])
def test_common_paraphrases_use_shared_intent_without_a_provider_call(goal):
    selected = profiles()
    intent = infer(goal, selected)
    assert intent and intent.read_only and intent.target_ids == [ID]
    row, rules, _ = selected[ID]
    assert relevant(goal, row, rules)


@pytest.mark.parametrize("goal", [
    "Liste meine Lampen und dimme sie auf 20 Prozent.", "Show my lights and dim them.",
    "Zeige meine Automationen und deaktiviere die defekten.",
])
def test_mixed_observation_and_changes_cannot_be_lowered_by_inventory_classifier(goal):
    selected = profiles()
    intent = infer(goal, selected)
    assert intent is None  # Semantic interpretation binds each requested subgoal.
    assert not ha_inventory_question(goal, [selected[ID][0]])


@pytest.mark.parametrize("goal", [
    "Welche Lampe soll ich kaufen?", "Welche meiner Lampen sollte ich kaufen?",
    "Wie konfiguriere ich Home Assistant?", "What is Home Assistant?",
])
def test_public_advice_has_no_private_target(goal):
    intent = infer(goal, profiles())
    assert intent and intent.mode == "explain" and not intent.target_ids


@pytest.mark.parametrize(("goal", "mode"), [
    ("Archiviere dieses Dokument in Paperless.", "admin"),
    ("Vergib das Tag Steuer für diese Rechnung.", "admin"),
    ("Welche Dokumente haben den Status bezahlt?", "observe"),
])
def test_paperless_nouns_and_actions_share_the_same_contract(goal, mode):
    intent = infer(goal, profiles("paperless"))
    assert intent and intent.mode == mode


@pytest.mark.parametrize("goal", [
    "Welche Gmail-Mails besitzen eine Antwort von mir?",
    "Which Gmail messages did I respond to?", "Welche Gmail-Mails habe ich beantwortet?",
])
def test_reply_requirement_is_independent_of_previous_guard_phrases(goal):
    intent = infer(goal, profiles("gmail"))
    assert intent and intent.requirements[0].kind == "mail_reply"


def test_unknown_wording_has_bounded_local_semantic_path_not_default_target_authority():
    selected = profiles()
    assert infer("Überblick bitte", selected) is None
    data = semantic_request("Überblick bitte", selected)
    assert data["data"]["label"] == "LOCAL_ONLY"
    assert set(data["data"]["targets"][0]) == {"id", "kind", "name"}
    assert "config" not in json.dumps(data["data"])
    payload = RequestIntent(target_ids=[ID], mode="observe", topic="inventory",
                            requirements=[Requirement(kind="entity_states", domain="light",
                                                      integration_id=ID)],
                            origin="semantic").model_dump()
    assert accept_semantic(payload, selected).read_only
    payload["target_ids"] = ["foreign"]
    with pytest.raises(ValueError):
        accept_semantic(payload, selected)


def test_semantic_fields_cannot_smuggle_execution_or_new_requirements():
    payload = RequestIntent(target_ids=[ID], mode="observe", topic="general",
                            origin="semantic").model_dump()
    with pytest.raises(ValueError):
        accept_semantic({**payload, "shell": "SYNTHETIC_COMMAND"}, profiles())
    with pytest.raises(ValueError):
        accept_semantic({**payload, "requirements": [
            {"kind": "connection", "integration_id": "foreign"}]}, profiles())


def interface(rules):
    return [{"integration_id": ID, "kind": "home_assistant", "rules": rules.model_dump()}]


def decision(tool, arguments):
    return {"kind": "tool", "message": "Synthetic read", "integration_id": ID,
            "tool": tool, "arguments": arguments}


def test_readonly_actual_grammar_rejects_post_and_webhook_while_admin_is_unchanged():
    rules = profiles()[ID][1]
    readonly = Draft202012Validator(decision_schema(
        [ID], ["http"], interface(rules), read_only=True,
    ))
    admin = Draft202012Validator(decision_schema([ID], ["http"], interface(rules)))
    post = decision("http", {"method": "POST", "path": "/api/services/light/turn_on",
                             "body": {"entity_id": "light.synthetic"}})
    admin.validate(post)
    for denied in [post, decision("http", {"method": "GET", "path": "/api/WebHook/synthetic"})]:
        with pytest.raises(ValidationError):
            readonly.validate(denied)
    readonly.validate(decision("http", {"method": "GET", "path": "/api/states"}))
    assert rules.http_methods == ["GET", "POST"]


def test_unbound_readonly_grammar_does_not_offer_http_write_variant():
    schema = decision_schema([ID], ["http"], read_only=True)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(decision("http", {"method": "POST", "path": "/api/"}))


def test_readonly_websocket_parameters_cannot_turn_supervisor_into_a_mutation():
    rules = Rules(enabled=True, ha_websocket_prefixes=["get_states", "supervisor/api", "config/"])
    validator = Draft202012Validator(decision_schema(
        [ID], ["ha.websocket"], interface(rules), read_only=True,
    ))
    validator.validate(decision("ha.websocket", {"type": "get_states", "parameters": {}}))
    validator.validate(decision("ha.websocket", {"type": "supervisor/api", "parameters": {
        "method": "get", "endpoint": "/info"}}))
    for args in [{"type": "get_states", "parameters": {"injected": True}},
                 {"type": "supervisor/api", "parameters": {"method": "post", "endpoint": "/info"}},
                 {"type": "config/entity_registry/update", "parameters": {}}]:
        with pytest.raises(ValidationError):
            validator.validate(decision("ha.websocket", args))


def test_effective_rules_preserve_only_existing_pinned_mcp_reads_and_no_new_scopes():
    rules = Rules(enabled=True, shell=True, mcp=True, mcp_read_tools={"read_email": "a" * 64},
                  mail_recipients=["synthetic@example.invalid"], http_methods=["POST"],
                  http_prefixes=["/api/"], file_upload=True)
    bounded = effective_rules(rules, read_only=True)
    assert not bounded.shell and not bounded.mcp and not bounded.mail_recipients
    assert not bounded.http_methods and not bounded.file_upload and bounded.max_effects == 0
    assert bounded.mcp_read_tools == rules.mcp_read_tools
    assert bounded.file_read_roots == ["/"]  # Already permitted by original shell authority.
    assert rules.shell and rules.mcp and rules.file_upload
    actual = effective_interfaces(interface(rules), read_only=True)[0]["rules"]
    assert actual == bounded.model_dump()


def step(path, body, *, inspection=False, status="succeeded", error=False):
    result = {"http_status": 200, "body": body}
    if error:
        result["projection_error"] = None
    return SimpleNamespace(kind="read", status=status, document=json.dumps({
        "integration_id": ID, "tool": "http", "capability_inspection": inspection,
        "arguments": {"method": "GET", "path": path},
    }), result=json.dumps(result))


def test_transport_success_or_bootstrap_does_not_prove_inventory():
    intent = infer("Welche Lampen habe ich?", profiles())
    bootstrap = step("/api/", {"message": "running"}, inspection=True)
    assert not adequacy(intent, [bootstrap])["satisfied"]
    assert not adequacy(intent, [step("/api/config", {"version": "synthetic"})])["satisfied"]
    rows = [{"entity_id": "light.synthetic", "state": "on"}]
    assert adequacy(intent, [step("/api/states", rows)])["satisfied"]
    assert not adequacy(intent, [step("/api/states", rows, error=True)])["satisfied"]
    assert not adequacy(intent, [step("/api/states", rows, status="failed")])["satisfied"]


def test_current_projection_matches_requested_domain_not_merely_some_states():
    intent = infer("Welche Lampen habe ich?", profiles())
    projection = {"items_path": "", "where_pointer": "/entity_id", "where_prefix": "sensor.",
                  "fields": ["/entity_id", "/state"], "limit": 100}
    receipt = step("/api/states", project([], projection))
    document = json.loads(receipt.document)
    document["arguments"]["projection"] = projection
    receipt.document = json.dumps(document)
    assert not adequacy(intent, [receipt])["satisfied"]
    projection["where_prefix"] = "light."
    document["arguments"]["projection"] = projection
    receipt.document = json.dumps(document)
    assert adequacy(intent, [receipt])["satisfied"]


def test_per_target_budgets_do_not_inherit_a_readonly_mailbox_zero():
    selected = profiles()
    selected["mailbox"] = (SimpleNamespace(kind="mcp"), Rules(enabled=True, max_effects=0), {})
    budgets = target_budgets(selected)
    assert budgets[ID]["max_effects"] == 5 and budgets["mailbox"]["max_effects"] == 0


def test_goal_specific_recovery_does_not_unlock_on_unrelated_config_response():
    from hub.agent_read_recovery import context

    intent = infer("Welche Lampen habe ich?", profiles()).model_dump()
    failure = step("/api/light", {}, status="failed")
    failure.sequence = 1
    failure.result = json.dumps({"http_status": 404, "failure_category": "not_found"})
    config = step("/api/config", {"version": "synthetic"})
    config.sequence = 2
    assert context([failure, config], request_intent=intent)["needs_alternative"]
    states = step("/api/states", [{"entity_id": "light.synthetic", "state": "on"}])
    states.sequence = 3
    assert not context([failure, config, states], request_intent=intent)["needs_alternative"]


def test_semantic_paraphrase_reuses_native_inventory_renderer_without_expanding_authority():
    from hub.agent_ha_inventory import plan

    selected = profiles()
    intent = RequestIntent(
        target_ids=[ID], mode="observe", topic="inventory", answer_kind="light_inventory",
        requirements=[Requirement(kind="entity_states", domain="light", integration_id=ID)],
        origin="semantic",
    )
    actual = plan("Kannst du mir meine Lampen auflisten?", selected,
                  request_intent=intent.model_dump())
    assert actual and actual["arguments"]["path"] == "/api/states"
    assert actual["arguments"]["projection"]["where_prefix"] == "light."
    intent.mode = "admin"
    assert plan("Lampen und dimmen", selected, request_intent=intent.model_dump()) is None
    selected[ID][1].http_methods = ["POST"]
    intent.mode = "observe"
    assert plan("Lampen", selected, request_intent=intent.model_dump()) is None


def test_access_intent_binds_only_the_named_current_target_not_every_manual_selection():
    from hub.agent_capabilities import request_intent

    selected = profiles()
    selected[ID][0].name = "Home Assistant"
    selected["ssh"] = (SimpleNamespace(kind="ssh", name="Mac mini"), Rules(enabled=True), {})
    intent = request_intent("Kannst du auf Home Assistant zugreifen?", selected)
    assert intent.target_ids == [ID]
    assert intent.requirements[0].kind == "connection"


def test_drive_descriptor_does_not_advertise_agent_administration_or_live_readiness():
    from hub.agent_capabilities import describe

    row = SimpleNamespace(kind="google_drive", name="Synthetic Drive", enabled=True)
    capabilities = describe(row, Rules(enabled=True))
    assert capabilities["inspection"] is None and capabilities["operations"] == {}
    assert not capabilities["readiness"]["live_access_verified"]
    assert "no general Drive chat administration" in capabilities["discovery"][0]


@pytest.mark.parametrize("goal", [
    "Welche Lampen gibt es in HA?", "Welche Lampen habe ich denn?",
    "Kannst du mir meine Lampen auflisten?", "Liste meine Lampen auf",
])
def test_shared_certain_light_intent_also_selects_the_actual_deterministic_renderer(goal):
    intent = infer(goal, profiles())
    assert intent and intent.answer_kind == "light_inventory"


@pytest.mark.parametrize("goal", [
    "Welche meiner Lampen sind im Wohnzimmer?",
    "Zeige meine Lampen und ihren Stromverbrauch.",
    "Welche Lampen habe ich? Erläutere den Energieverbrauch.",
])
def test_extra_filters_or_goals_require_semantic_interpretation_not_partial_native_answer(goal):
    assert infer(goal, profiles()) is None


@pytest.mark.parametrize(("goal", "document"), [
    ("Welche Version hat Paperless?", False),
    ("Prüfe die Service Health von Paperless", False),
    ("Welche Dokumente haben den Status bezahlt?", True),
    ("Welchen Status hat meine Rechnung in Paperless?", True),
    ("Finde meine Versicherungsunterlagen", True),
    ("Archiviere dieses Dokument", False),
    ("Vergib das Tag Steuer", False),
    ("Liste meine Dokumente und lösche die Duplikate", False),
])
def test_shared_paperless_document_read_and_service_metadata_are_distinct(goal, document):
    from hub.agent_intent import paperless_document_request

    assert paperless_document_request(goal) is document


@pytest.mark.parametrize("goal", [
    "Zeige meine Sensoren und verknüpfe sie neu",
    "Prüfe Home Assistant und recherchiere die aktuelle Version.",
    "Show my sensors, pair them afterwards",
])
def test_unrecognized_compound_actions_or_research_use_semantic_contract(goal):
    assert infer(goal, profiles()) is None
    contract = semantic_request(goal, profiles())
    assert contract["data"]["goal"] == goal and contract["data"]["label"] == "LOCAL_ONLY"


def test_malformed_success_receipt_cannot_become_goal_evidence_or_crash_the_checker():
    intent = infer("Welche Lampen habe ich?", profiles())
    receipt = step("/api/states", [])
    receipt.result = "not-json"
    assert not adequacy(intent, [receipt])["satisfied"]
    receipt.result = "[]"
    assert not adequacy(intent, [receipt])["satisfied"]


def test_explicit_proton_account_excludes_other_mailboxes_in_shared_intent():
    rules = Rules(enabled=True, mcp_read_tools={"list_emails": "a" * 64})
    selected = {
        "proton": (SimpleNamespace(kind="mcp", name="Proton Bridge"), rules, {}),
        "other": (SimpleNamespace(kind="mcp", name="Other mailbox"), rules, {}),
        "gmail": (SimpleNamespace(kind="gmail", name="Gmail"),
                  Rules(enabled=True, gmail_read=True), {}),
    }
    intent = infer("Welche neuen Mails gibt es bei Proton?", selected)
    assert intent and intent.target_ids == ["proton"]


@pytest.mark.parametrize("verified", [False, True])
def test_pure_administration_needs_bound_verified_effect_not_a_native_document_read(verified):
    intent = infer("Rename the Paperless document", profiles("paperless"))
    assert intent and [item.kind for item in intent.requirements] == ["effect_postcondition"]
    effect = step("/api/documents/1/", {})
    effect.kind = "effect"
    effect.result = json.dumps({"effect_verified": verified})
    assert adequacy(intent, [effect])["satisfied"] is verified
    assert not adequacy(intent, [step("/api/", {}, inspection=True)])["satisfied"]


def test_mixed_observation_and_change_requires_both_distinct_evidence_types():
    assert infer("Liste meine Lampen und dimme sie", profiles()) is None
    intent = RequestIntent(target_ids=[ID], mode="admin", topic="inventory", requirements=[
        Requirement(kind="entity_states", domain="light", integration_id=ID),
        Requirement(kind="effect_postcondition", integration_id=ID),
    ])
    assert intent and {item.kind for item in intent.requirements} == {
        "entity_states", "effect_postcondition",
    }
    effect = step("/api/services/light/turn_on", {})
    effect.kind = "effect"
    effect.result = json.dumps({"effect_verified": True})
    assert not adequacy(intent, [effect])["satisfied"]
    states = step("/api/states", [{"entity_id": "light.synthetic", "state": "on"}])
    assert adequacy(intent, [effect, states])["satisfied"]


@pytest.mark.parametrize("goal", [
    "Welches Backup ist in Home Assistant vorhanden?",
    "Zeige den Status der Migration in Home Assistant.",
    "What is the status of the update in Home Assistant?",
    "Backup in Home Assistant", "Migration Home Assistant", "Wartung Home Assistant",
    "Zeige Sensoren in Home Assistant und starte Home Assistant neu.",
    "Starte Home Assistant neu und zeige Sensoren in Home Assistant.",
])
def test_change_nouns_and_compound_goals_never_mint_administration_shortcuts(goal):
    selected = profiles()
    selected["second"] = (SimpleNamespace(
        id="second", kind="home_assistant", name="Other Home Assistant", enabled=True,
    ), selected[ID][1], {})
    intent = infer(goal, selected)
    assert intent is None


def test_explicit_single_imperative_administration_keeps_its_bound_change_contract():
    intent = infer("Bitte starte Home Assistant neu.", profiles())
    assert intent and intent.mode == "admin"
    assert [requirement.kind for requirement in intent.requirements] == ["effect_postcondition"]


def test_administration_with_multiple_same_kind_candidates_needs_semantic_target_binding():
    selected = profiles()
    selected["other"] = (SimpleNamespace(
        id="other", kind="home_assistant", name="Other installation", enabled=True,
    ), selected[ID][1], {})
    assert infer("Bitte starte Home Assistant neu.", selected) is None


def test_semantic_grammar_requires_model_fields_and_application_stamps_its_own_provenance():
    contract = semantic_request("Überblick bitte", profiles())
    schema = contract["schema"]
    assert "origin" not in schema["properties"] and "version" not in schema["properties"]
    assert set(schema["required"]) == set(schema["properties"])
    expected = RequestIntent(target_ids=[ID], mode="observe", topic="inventory",
                             requirements=[Requirement(kind="entity_states", domain="light",
                                                       integration_id=ID)])
    payload = expected.model_dump(exclude={"origin", "version"})
    Draft202012Validator(schema).validate(payload)
    accepted = accept_semantic(payload, profiles())
    assert accepted.origin == "semantic" and accepted.version == 1
    for field in schema["required"]:
        incomplete = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValueError):
            accept_semantic(incomplete, profiles())
    assert accept_semantic({**payload, "origin": "shortcut", "version": 999}, profiles()).origin \
        == "semantic"


def test_entity_domain_required_in_semantic_schema_and_backend_validation():
    payload = RequestIntent(target_ids=[ID], mode="observe", topic="inventory",
                             requirements=[Requirement(kind="entity_states", domain="light",
                                                       integration_id=ID)]).model_dump()
    payload["requirements"][0]["domain"] = ""
    with pytest.raises(ValueError):
        accept_semantic(payload, profiles())
    model_payload = {key: value for key, value in payload.items()
                     if key not in {"origin", "version"}}
    with pytest.raises(ValidationError):
        Draft202012Validator(semantic_request("Test", profiles())["schema"]).validate(model_payload)


def test_semantic_prior_context_is_explicit_current_and_does_not_create_new_targets():
    request = semantic_request("Welche davon?", profiles(), prior_target_ids=[ID])
    assert request["data"]["prior_displayed_target_ids"] == [ID]
    assert semantic_request("Welche davon?", profiles())["data"]["prior_displayed_target_ids"] == []
    with pytest.raises(ValueError):
        semantic_request("Welche davon?", profiles(), prior_target_ids=["foreign"])


def test_document_content_requires_an_actual_current_document_body_not_search_metadata():
    intent = RequestIntent(
        target_ids=[ID], mode="observe", topic="documents",
        requirements=[Requirement(kind="document_content", integration_id=ID)],
    )
    receipt = step("/api/", {})
    receipt.document = json.dumps({"integration_id": ID, "tool": "paperless.read",
                                   "arguments": {"operation": "search", "page": 1, "limit": 10}})
    receipt.result = json.dumps({"label": "LOCAL_ONLY", "operation": "search", "data": {
        "count": 1, "results": [{"id": 7, "title": "Contract", "tags": []}],
        "page": 1, "page_size": 10, "has_next": False,
    }})
    assert not adequacy(intent, [receipt])["satisfied"]
    receipt.document = json.dumps({"integration_id": ID, "tool": "paperless.read",
                                   "arguments": {"operation": "document", "document_id": 7}})
    receipt.result = json.dumps({"label": "LOCAL_ONLY", "operation": "document", "data": {
        "id": 7, "title": "Contract", "tags": [], "content": "Actual synthetic OCR: 17 days.",
    }})
    assert adequacy(intent, [receipt])["satisfied"]
    value = json.loads(receipt.result)
    value["data"].pop("content")
    receipt.result = json.dumps(value)
    assert not adequacy(intent, [receipt])["satisfied"]


def test_content_without_unambiguous_resource_reference_goes_to_shared_semantic_stage():
    assert infer("Was steht in meinem Vertrag in Paperless?", profiles("paperless")) is None
    intent = infer("Lies Dokument-ID 7 in Paperless.", profiles("paperless"))
    assert intent and intent.requirements[0].kind == "document_content"
