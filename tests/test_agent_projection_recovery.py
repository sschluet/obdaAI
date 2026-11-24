"""Only one proven projection failure permits a bounded corrected read."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from hub.agent_read_recovery import context, repeats_attempt
from hub.agent_tools import Rules, validate_tool

ARGS = {
    "method": "GET",
    "path": "/api/config",
    "projection": {"items_path": "", "fields": ["/version"], "limit": 100},
}
RESULT = {
    "http_status": 200,
    "body": {"version": "synthetic"},
    "projection_error": "invalid_projection",
    "failure_category": "validation_error",
    "failure_phase": "projection",
}


def step(
    *,
    sequence=1,
    kind="read",
    status="failed",
    arguments=None,
    result=None,
    tool="http",
    target="synthetic",
):
    return SimpleNamespace(
        sequence=sequence,
        kind=kind,
        status=status,
        document=json.dumps(
            {
                "integration_id": target,
                "tool": tool,
                "arguments": ARGS if arguments is None else arguments,
            }
        ),
        result=json.dumps(RESULT if result is None else result),
    )


def test_projection_failure_preserved_and_corrected_same_path_is_not_replay():
    original = step()
    before = deepcopy(vars(original))
    repair = context([original])
    assert repair["recovery_kind"] == "projection" and repair["needs_alternative"]
    assert vars(original) == before
    assert repeats_attempt(repair, "synthetic", "http", ARGS)
    # Default-equivalent normalized args cannot evade the repeat guard.
    same = deepcopy(ARGS)
    same.update(query={}, body=None, verification=None)
    same["projection"].update(where_pointer=None, where_prefix=None, where_equals=None)
    assert repeats_attempt(repair, "synthetic", "http", same)
    corrected = {"method": "GET", "path": "/api/config"}
    assert not repeats_attempt(repair, "synthetic", "http", corrected)
    assert not repeats_attempt(repair, "synthetic", "http", {**corrected, "path": "/api/states"})
    assert not repeats_attempt(repair, "other", "http", ARGS)
    assert not repeats_attempt(repair, "synthetic", "http.verify", ARGS)
    # This hint gives no write capability or scope expansion.
    rules = Rules(enabled=True, http_methods=["GET"], http_prefixes=["/api/"])
    _, effect = validate_tool("home_assistant", rules, "http", corrected)
    assert not effect
    with pytest.raises(PermissionError):
        validate_tool("home_assistant", rules, "http", {"method": "POST", "path": "/api/config"})


@pytest.mark.parametrize("body", [{"version": "synthetic"}, [{"entity_id": "update.synthetic"}]])
def test_only_successful_corrected_read_completes_recovery(body):
    corrected = step(
        sequence=2,
        status="succeeded",
        arguments={"method": "GET", "path": "/api/config"},
        result={"http_status": 200, "body": body},
    )
    assert context([step(), corrected])["needs_alternative"] is False
    same = step(sequence=2, status="succeeded", result={"http_status": 200, "body": body})
    assert context([step(), same])["needs_alternative"] is True
    foreign = step(
        sequence=2,
        status="succeeded",
        target="other",
        arguments={"method": "GET", "path": "/api/config"},
        result={"http_status": 200, "body": body},
    )
    assert context([step(), foreign])["needs_alternative"] is True


@pytest.mark.parametrize(
    "change",
    [
        {"http_status": 401},
        {"http_status": 403},
        {"http_status": 404},
        {"http_status": "200"},
        {"http_status": True},
        {"http_status": 300},
        {"failure_category": "timeout"},
        {"failure_category": "not_found"},
        {"failure_phase": "transport"},
        {"body": None},
        {"body": "raw text"},
    ],
)
def test_other_failures_are_not_projection_recovery(change):
    assert context([step(result={**RESULT, **change})]) is None


@pytest.mark.parametrize(
    "case",
    [
        "private",
        "uncertain",
        "post",
        "effect",
        "before_effect",
        "second_failure",
        "other_uncertain",
        "missing_marker",
        "missing_projection",
        "invalid_arguments",
    ],
)
def test_closed_recovery_boundaries(case):
    failed = step()
    history = [failed]
    private = False
    if case == "private":
        private = True
    elif case == "uncertain":
        failed.status = "uncertain"
    elif case == "post":
        failed = step(arguments={**ARGS, "method": "POST"})
        history = [failed]
    elif case in {"effect", "before_effect"}:
        history.append(
            step(sequence=2 if case == "effect" else 0, kind="effect", status="succeeded")
        )
    elif case in {"second_failure", "other_uncertain"}:
        history.append(
            step(sequence=2, status="failed" if case == "second_failure" else "uncertain")
        )
    elif case == "missing_marker":
        result = dict(RESULT)
        result.pop("projection_error")
        history = [step(result=result)]
    elif case == "missing_projection":
        history = [step(arguments={"method": "GET", "path": "/api/config"})]
    else:
        history = [step(arguments={**ARGS, "path": "https://unauthorized.invalid"})]
    assert context(history, private_read=private) is None


def test_404_path_repair_contract_is_unchanged():
    failed = step(
        arguments={"method": "GET", "path": "/api/light"},
        result={"http_status": 404, "failure_category": "not_found"},
    )
    recovery = context([failed])
    assert recovery["recovery_kind"] == "not_found"
    assert repeats_attempt(
        recovery,
        "synthetic",
        "http",
        {"method": "GET", "path": "/api/light", "query": {"different": True}},
    )
    assert not repeats_attempt(
        recovery, "synthetic", "http", {"method": "GET", "path": "/api/states"}
    )


def test_adequacy_not_just_http_success_is_required(monkeypatch):
    import hub.agent_intent as intent

    corrected = step(
        sequence=2,
        status="succeeded",
        arguments={"method": "GET", "path": "/api/config"},
        result={"http_status": 200, "body": {"version": "synthetic"}},
    )
    seen = []

    def inadequate(contract, receipts):
        seen.extend(receipts)
        return {"satisfied": False}

    monkeypatch.setattr(intent, "adequacy", inadequate)
    assert context([step(), corrected], request_intent={"synthetic": True})["needs_alternative"]
    assert seen == [corrected]


def test_projection_replay_equality_preserves_json_boolean_number_types():
    failed_arguments = {**ARGS, "query": {"enabled": False, "limit": 0}}
    recovery = context([step(arguments=failed_arguments)])
    assert repeats_attempt(recovery, "synthetic", "http", failed_arguments)
    assert not repeats_attempt(
        recovery, "synthetic", "http", {**failed_arguments, "query": {"enabled": 0, "limit": 0}}
    )
    assert not repeats_attempt(
        recovery,
        "synthetic",
        "http",
        {**failed_arguments, "query": {"enabled": False, "limit": False}},
    )
    same = deepcopy(failed_arguments)
    same.pop("method")
    assert repeats_attempt(recovery, "synthetic", "http", same)


def test_second_projection_failure_is_terminal_even_for_modified_arguments():
    corrected_but_failed = step(
        sequence=2,
        arguments={**ARGS, "projection": {"items_path": "/version", "fields": [], "limit": 100}},
    )
    assert context([step(), corrected_but_failed]) is None


def admin_intent(*extra, confidence="certain"):
    from hub.agent_intent import RequestIntent, Requirement

    return RequestIntent(
        target_ids=["synthetic"],
        mode="admin",
        topic="system",
        confidence=confidence,
        requirements=[
            Requirement(kind="system", integration_id="synthetic"),
            Requirement(kind="effect_postcondition", integration_id="synthetic"),
            *extra,
        ],
    ).model_dump()


def test_corrected_read_resolves_admin_prerequisite_not_future_effect_requirement():
    from hub.agent_intent import adequacy

    contract = admin_intent()
    before = deepcopy(contract)
    corrected = step(
        sequence=2,
        status="succeeded",
        arguments={"method": "GET", "path": "/api/config"},
        result={"http_status": 200, "body": {"version": "synthetic"}},
    )
    assert context([step(), corrected], request_intent=contract)["needs_alternative"] is False
    assert contract == before
    full = adequacy(contract, [corrected])
    assert full["satisfied"] is False
    assert [item["kind"] for item in full["missing"]] == ["effect_postcondition"]
    assert not adequacy(
        contract,
        [
            corrected,
            step(sequence=3, kind="effect", status="succeeded", result={"effect_verified": False}),
        ],
    )["satisfied"]
    verified = step(sequence=3, kind="effect", status="succeeded", result={"effect_verified": True})
    assert adequacy(contract, [corrected, verified])["satisfied"] is True


def test_admin_read_prerequisite_keeps_other_domain_requirements():
    from hub.agent_intent import Requirement

    contract = admin_intent(
        Requirement(kind="entity_states", integration_id="synthetic", domain="light")
    )
    corrected = step(
        sequence=2,
        status="succeeded",
        arguments={"method": "GET", "path": "/api/config"},
        result={"http_status": 200, "body": {"version": "synthetic"}},
    )
    assert context([step(), corrected], request_intent=contract)["needs_alternative"] is True
    wrong_domain = step(
        sequence=3,
        status="succeeded",
        arguments={
            "method": "GET",
            "path": "/api/states",
            "projection": {
                "items_path": "",
                "where_pointer": "/entity_id",
                "where_prefix": "sensor.",
                "fields": ["/entity_id", "/state"],
                "limit": 100,
            },
        },
        result={
            "http_status": 200,
            "body": {
                "items": [{"/entity_id": "sensor.synthetic", "/state": "20"}],
                "matched": 1,
                "returned": 1,
            },
        },
    )
    assert context([step(), corrected, wrong_domain], request_intent=contract)["needs_alternative"]
    observed = step(
        sequence=4,
        status="succeeded",
        arguments={
            "method": "GET",
            "path": "/api/states",
            "projection": {
                "items_path": "",
                "where_pointer": "/entity_id",
                "where_prefix": "light.",
                "fields": ["/entity_id", "/state"],
                "limit": 100,
            },
        },
        result={
            "http_status": 200,
            "body": {
                "items": [{"/entity_id": "light.synthetic", "/state": "on"}],
                "matched": 1,
                "returned": 1,
            },
        },
    )
    assert not context([step(), corrected, wrong_domain, observed], request_intent=contract)[
        "needs_alternative"
    ]


def test_uncertain_admin_does_not_derive_read_only_prerequisite_view():
    corrected = step(
        sequence=2,
        status="succeeded",
        arguments={"method": "GET", "path": "/api/config"},
        result={"http_status": 200, "body": {"version": "synthetic"}},
    )
    assert (
        context([step(), corrected], request_intent=admin_intent(confidence="uncertain"))[
            "needs_alternative"
        ]
        is True
    )


def test_admin_multi_target_reads_resolve_without_requiring_future_effect():
    from hub.agent_intent import RequestIntent, Requirement, adequacy

    contract = RequestIntent(
        target_ids=["synthetic", "secondary"],
        mode="admin",
        topic="system",
        requirements=[
            Requirement(kind="system", integration_id=target)
            for target in ["synthetic", "secondary"]
        ]
        + [Requirement(kind="effect_postcondition", integration_id="synthetic")],
    ).model_dump()
    before = deepcopy(contract)
    primary = step(
        sequence=2,
        status="succeeded",
        arguments={"method": "GET", "path": "/api/config"},
        result={"http_status": 200, "body": {"version": "synthetic"}},
    )
    secondary = step(
        sequence=3,
        status="succeeded",
        target="secondary",
        arguments={"method": "GET", "path": "/api/config"},
        result={"http_status": 200, "body": {"ready": True}},
    )
    assert context([step(), primary], request_intent=contract)["needs_alternative"]
    assert not context([step(), primary, secondary], request_intent=contract)["needs_alternative"]
    assert contract == before
    assert not adequacy(contract, [primary, secondary])["satisfied"]
    verified = step(sequence=4, kind="effect", status="succeeded", result={"effect_verified": True})
    assert adequacy(contract, [primary, secondary, verified])["satisfied"]
    # A previous effect is never turned into permission for a recovery episode.
    assert (
        context(
            [
                step(
                    sequence=0, kind="effect", status="succeeded", result={"effect_verified": True}
                ),
                step(),
                primary,
                secondary,
            ],
            request_intent=contract,
        )
        is None
    )


def test_other_target_adequacy_cannot_replace_changed_read_on_failed_target():
    from hub.agent_intent import RequestIntent, Requirement

    contract = RequestIntent(
        target_ids=["synthetic", "secondary"],
        mode="admin",
        topic="system",
        requirements=[
            Requirement(kind="system", integration_id="secondary"),
            Requirement(kind="effect_postcondition", integration_id="synthetic"),
        ],
    ).model_dump()
    secondary = step(
        sequence=2,
        status="succeeded",
        target="secondary",
        arguments={"method": "GET", "path": "/api/config"},
        result={"http_status": 200, "body": {"ready": True}},
    )
    assert context([step(), secondary], request_intent=contract)["needs_alternative"]


@pytest.mark.parametrize("effect_status", ["prepared", "succeeded"])
def test_effect_after_resolved_projection_recovery_does_not_reopen_episode(effect_status):
    contract = admin_intent()
    corrected = step(
        sequence=2,
        status="succeeded",
        arguments={"method": "GET", "path": "/api/services"},
        result={"http_status": 200, "body": [{"domain": "synthetic"}]},
    )
    future = step(
        sequence=3,
        kind="effect",
        status=effect_status,
        result={"effect_verified": effect_status == "succeeded"},
    )
    assert not context([step(), corrected, future], request_intent=contract)["needs_alternative"]
    earlier = step(
        sequence=0,
        kind="effect",
        status=effect_status,
        result={"effect_verified": effect_status == "succeeded"},
    )
    assert context([earlier, step(), corrected], request_intent=contract) is None


def test_uncertain_effect_after_corrected_read_still_stops_recovery():
    corrected = step(
        sequence=2,
        status="succeeded",
        arguments={"method": "GET", "path": "/api/services"},
        result={"http_status": 200, "body": [{"domain": "synthetic"}]},
    )
    uncertain = step(
        sequence=3, kind="effect", status="uncertain", result={"effect_verified": False}
    )
    assert context([step(), corrected, uncertain], request_intent=admin_intent()) is None
