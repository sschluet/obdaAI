"""Optional operator prerequisites need authentic same-job/target independent evidence."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from hub.action_api import digest, encode
from hub.agent_prerequisites import check, missing, planning_context, validate_policy
from hub.agent_tools import Rules, effective_rules, validate_tool
from pydantic import ValidationError

RULE = {
    "operation": {"tool": "http", "method": "POST", "path": "/api/services/update/install"},
    "requires": {"tool": "http", "method": "POST", "path": "/api/services/backup/create"},
}
UPDATE = {"method": "POST", "path": RULE["operation"]["path"]}


def rules(**updates):
    return Rules(
        enabled=True,
        http_methods=["GET", "POST"],
        http_prefixes=["/api/"],
        effect_prerequisites=[RULE],
        **updates,
    )


def step(sequence, kind, document, result, *, job_id="job", status="succeeded"):
    document = encode(document)
    return SimpleNamespace(
        sequence=sequence,
        kind=kind,
        document=document,
        sha256=digest(document),
        result=encode(result),
        job_id=job_id,
        status=status,
    )


def receipts(*, manual=False, websocket=False):
    arguments = {
        "method": "POST",
        "path": RULE["requires"]["path"],
        "verification": {
            "path": "/api/states/sensor.backup",
            "query": {},
            "expected": {"/body/state": "ready"},
        },
    }
    document = {"integration_id": "ha", "tool": "http", "arguments": arguments}
    if websocket:
        document = {
            "integration_id": "ha",
            "tool": "ha.websocket",
            "arguments": {
                "type": "call_service",
                "parameters": {"domain": "backup", "service": "create"},
            },
        }
        manual = True
    effect = step(1, "effect", document, {"effect_verified": True, "verification_step": 2})
    verification = (
        step(
            2,
            "read",
            {
                "integration_id": "ha",
                "tool": "http.verify",
                "arguments": {
                    "effect_step": 1,
                    "path": "/api/states/sensor.backup",
                    "expected": {"/body/state": "ready"},
                },
            },
            {"verification_passed": True},
        )
        if manual
        else step(
            2,
            "verification",
            {"effect_step": 1, "predicate": arguments["verification"]},
            {"effect_verified": True},
        )
    )
    return [effect, verification]


@pytest.mark.parametrize("manual,websocket", [(False, False), (True, False), (True, True)])
def test_only_original_independently_verified_same_job_operation_satisfies_rule(manual, websocket):
    history = receipts(manual=manual, websocket=websocket)
    assert missing(history, "ha", rules(), "http", UPDATE, job_id="job") == []
    check(history, "ha", rules(), "http", UPDATE, job_id="job")
    assert missing(history, "other", rules(), "http", UPDATE, job_id="job") == [RULE["requires"]]
    assert missing(history, "ha", rules(), "http", UPDATE, job_id="other-job") == [RULE["requires"]]


@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "target",
        "job",
        "effect_status",
        "effect_flag",
        "proof_status",
        "proof_flag",
        "proof_ref",
        "proof_hash",
        "proof_missing",
        "predicate",
        "sequence_bool",
    ],
)
def test_claims_tampering_and_incomplete_verification_never_satisfy_prerequisite(change):
    history = receipts()
    effect, proof = history
    if change == "hash":
        effect.sha256 = "0" * 64
    elif change == "target":
        doc = json.loads(effect.document)
        doc["integration_id"] = "foreign"
        effect.document = encode(doc)
        effect.sha256 = digest(effect.document)
    elif change == "job":
        proof.job_id = "foreign"
    elif change == "effect_status":
        effect.status = "uncertain"
    elif change == "effect_flag":
        effect.result = encode({"effect_verified": False, "verification_step": 2})
    elif change == "proof_status":
        proof.status = "failed"
    elif change == "proof_flag":
        proof.result = encode({"effect_verified": False})
    elif change in {"proof_ref", "predicate"}:
        doc = json.loads(proof.document)
        if change == "proof_ref":
            doc["effect_step"] = 99
        else:
            doc["predicate"] = {"invented": "value"}
        proof.document = encode(doc)
        proof.sha256 = digest(proof.document)
    elif change == "proof_hash":
        proof.sha256 = "0" * 64
    elif change == "proof_missing":
        history.pop()
    else:
        effect.result = encode({"effect_verified": True, "verification_step": True})
    with pytest.raises(PermissionError):
        check(history, "ha", rules(), "http", UPDATE, job_id="job")


def test_websocket_equivalence_tightens_only_same_service_identity_without_rights_or_rewrite():
    arguments = {
        "type": "call_service",
        "parameters": {
            "domain": "update",
            "service": "install",
            "service_data": {"entity_id": "update.x"},
        },
    }
    original = deepcopy(arguments)
    assert missing([], "ha", rules(), "ha.websocket", arguments, job_id="job") == [RULE["requires"]]
    assert not missing(receipts(), "ha", rules(), "ha.websocket", arguments, job_id="job")
    assert arguments == original
    for command in ["supervisor/api", "update/install"]:
        assert not missing([], "ha", rules(), "ha.websocket", {"type": command}, job_id="job")
    with pytest.raises(PermissionError):
        validate_tool("home_assistant", rules(), "ha.websocket", arguments)


def test_optional_default_and_derived_read_only_ceiling_do_not_invent_writes():
    assert Rules().effect_prerequisites == []
    value = rules()
    view = effective_rules(value, read_only=True)
    assert value.effect_prerequisites and view.effect_prerequisites == []
    assert view.max_effects == 0 and view.http_methods == ["GET"]
    Rules.model_validate(view.model_dump())
    with pytest.raises(PermissionError):
        validate_tool("home_assistant", view, "http", UPDATE)


@pytest.mark.parametrize("invalid", ["method", "path", "self", "cycle", "absolute", "read"])
def test_impossible_or_unbounded_policies_are_rejected_clearly(invalid):
    rule = deepcopy(RULE)
    settings = {
        "enabled": True,
        "http_methods": ["GET", "POST"],
        "http_prefixes": ["/api/"],
        "effect_prerequisites": [rule],
    }
    if invalid == "method":
        settings["http_methods"] = ["GET"]
    elif invalid == "path":
        rule["requires"]["path"] = "/outside/"
    elif invalid == "self":
        rule["requires"] = deepcopy(rule["operation"])
    elif invalid == "cycle":
        settings["effect_prerequisites"].append(
            {
                "operation": deepcopy(rule["requires"]),
                "requires": deepcopy(rule["operation"]),
            }
        )
    elif invalid == "absolute":
        rule["requires"]["path"] = "https://example.invalid/x"
    else:
        rule["operation"] = {"tool": "http", "method": "GET", "path": "/api/states"}
    with pytest.raises((ValidationError, ValueError)):
        validate_policy("home_assistant", Rules.model_validate(settings))


def test_planning_context_exposes_only_operator_rule_and_actual_receipt_status():
    profile = SimpleNamespace(kind="home_assistant", enabled=True, writes_enabled=True)
    profiles = {"ha": (profile, rules(), {})}
    pending = planning_context([], profiles, job_id="job")[0]
    assert pending == {
        "integration_id": "ha",
        **RULE,
        "satisfied": False,
        "receipt_sequence": None,
        "permission_available": True,
    }
    done = planning_context(receipts(), profiles, job_id="job")[0]
    assert done["satisfied"] and done["receipt_sequence"] == 1
