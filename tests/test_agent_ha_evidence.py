import copy
import json
from types import SimpleNamespace

import pytest
from hub.agent_ha_evidence import evidence_satisfied, states_snapshot, summary


def receipt(rows=None, *, ws=False, projected=False, sequence=1):
    rows = [] if rows is None else rows
    args = (
        {"type": "get_states", "parameters": {}}
        if ws
        else {
            "method": "GET",
            "path": "/api/states",
            "query": {},
            "verification": None,
            "projection": None,
        }
    )
    result = {"response": rows} if ws else {"http_status": 200, "body": rows}
    if projected:
        args["projection"] = {
            "items_path": "",
            "where_pointer": "/entity_id",
            "where_prefix": "update.",
            "where_equals": None,
            "fields": ["/entity_id", "/state", "/attributes/installed_version"],
            "limit": 100,
        }
        result["body"] = {"items": rows, "matched": len(rows), "returned": len(rows)}
    return SimpleNamespace(
        kind="read",
        status="succeeded",
        sequence=sequence,
        document=json.dumps(
            {"tool": "ha.websocket" if ws else "http", "integration_id": "ha", "arguments": args}
        ),
        result=json.dumps(result),
    )


@pytest.mark.parametrize("ws", [False, True])
def test_complete_states_and_versions_render_only_observations(ws):
    original = [
        {"entity_id": "sensor.other", "state": "42"},
        {
            "entity_id": "update.core",
            "state": "on",
            "attributes": {
                "friendly_name": "Core",
                "installed_version": "1",
                "latest_version": "2",
                "in_progress": False,
                "supported_features": 0,
                "title": None,
            },
        },
        {"entity_id": "update.addon", "state": "off"},
    ]
    step = receipt(original, ws=ws)
    before = copy.deepcopy(vars(step))
    snap = states_snapshot([step], "ha", "update")
    assert snap and snap["complete"] and snap["pending"] == ["update.core"]
    assert snap["current"] == ["update.addon"]
    assert snap["entities"][0]["attributes"]["in_progress"] is False
    assert snap["entities"][0]["attributes"]["supported_features"] == 0
    assert snap["entities"][0]["attributes"]["title"] is None
    assert len(snap["result_sha256"]) == 64 and snap["sequence"] == 1
    text = summary([step], "ha")
    assert text and "Core" in text and "1 → 2" in text and "update.core" in text
    assert vars(step) == before


@pytest.mark.parametrize("ws", [False, True])
@pytest.mark.parametrize("rows", [[], [{"entity_id": "update.core", "state": "off"}]])
def test_complete_empty_or_off_evidence_scoped_no_update_statement(ws, rows):
    step = receipt(rows, ws=ws)
    assert evidence_satisfied([step], "ha", "update")
    text = summary([step], "ha")
    assert text and (
        "keine verfügbaren Updates" in text or "keine Update-Statusinformationen" in text
    )
    assert "Installation" not in text


def test_unknown_is_not_no_updates():
    step = receipt(
        [
            {"entity_id": "update.core", "state": "unknown"},
            {"entity_id": "update.addon", "state": "unavailable"},
        ]
    )
    assert evidence_satisfied([step], "ha", "update")
    text = summary([step], "ha")
    assert (
        text and "aktuell keine verfügbaren Updates" not in text and "kein Status verfügbar" in text
    )


def test_projected_complete_root_domain_and_scalars():
    step = receipt(
        [{"/entity_id": "update.core", "/state": "on", "/attributes/installed_version": None}],
        projected=True,
    )
    snap = states_snapshot([step], "ha", "update")
    assert snap and snap["entities"][0]["attributes"]["installed_version"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d, r: d["arguments"].update(path="/api/config"),
        lambda d, r: d["arguments"].update(query={"filter": "x"}),
        lambda d, r: d["arguments"]["projection"].update(items_path="/items"),
        lambda d, r: d["arguments"]["projection"].update(where_equals="update.core"),
        lambda d, r: d["arguments"]["projection"].update(where_prefix="update.core"),
        lambda d, r: d["arguments"]["projection"].update(fields=["/entity_id"]),
        lambda d, r: r["body"].update(matched=2),
        lambda d, r: r["body"].update(matched=True),
        lambda d, r: r["body"].update(returned=True),
        lambda d, r: r.update(projection_error={"message": "bad"}),
        lambda d, r: r.update(http_status=401),
        lambda d, r: r.update(model_view_only=True),
        lambda d, r: r.update(uncertain=True),
        lambda d, r: r["body"]["items"][0].update({"/state": None}),
    ],
)
def test_incomplete_filtered_invalid_or_model_views_never_prove_complete(mutation):
    step = receipt([{"/entity_id": "update.core", "/state": "on"}], projected=True)
    d, r = json.loads(step.document), json.loads(step.result)
    mutation(d, r)
    step.document, step.result = json.dumps(d), json.dumps(r)
    assert not evidence_satisfied([step], "ha", "update")
    assert summary([step], "ha") is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        ("status", "uncertain"),
        ("kind", "model"),
        ("kind", "effect"),
        ("sequence", True),
    ],
)
def test_only_successful_current_target_read(field, value):
    step = receipt([])
    setattr(step, field, value)
    assert not evidence_satisfied([step], "ha", "update")
    assert not evidence_satisfied([receipt([])], "other", "update")


def test_ws_wrong_command_and_nonlist_rejected():
    step = receipt([], ws=True)
    d = json.loads(step.document)
    d["arguments"]["type"] = "supervisor/api"
    step.document = json.dumps(d)
    assert not evidence_satisfied([step], "ha", "update")
    assert not evidence_satisfied([receipt({"version": "1"}, ws=True)], "ha", "update")


def test_latest_observed_snapshot_wins_no_reuse_other_job_views():
    a = receipt([{"entity_id": "update.core", "state": "on"}], sequence=1)
    b = receipt([{"entity_id": "update.core", "state": "off"}], sequence=3)
    assert states_snapshot([b, a], "ha", "update")["pending"] == []
    assert states_snapshot([], "ha", "update") is None


def test_snapshot_before_effect_is_not_current_post_effect_state():
    old = receipt([{"entity_id": "update.core", "state": "on"}], sequence=1)
    effect = SimpleNamespace(kind="effect", status="uncertain", sequence=2)
    assert states_snapshot([old, effect], "ha", "update") is None
    fresh = receipt([{"entity_id": "update.core", "state": "off"}], sequence=3)
    assert states_snapshot([old, effect, fresh], "ha", "update")["current"] == ["update.core"]


@pytest.mark.parametrize("marker", ["projection_error", "truncated", "partial"])
def test_explicit_incomplete_result_not_evidence(marker):
    step = receipt([])
    result = json.loads(step.result)
    result[marker] = {} if marker == "projection_error" else True
    step.result = json.dumps(result)
    assert not evidence_satisfied([step], "ha", "update")


def test_duplicate_or_malformed_raw_rows_cannot_prove_complete_domain():
    row = {"entity_id": "update.core", "state": "on"}
    for rows in ([row, row], [row, {"entity_id": "sensor.x", "state": None}]):
        assert not evidence_satisfied([receipt(rows)], "ha", "update")


def test_real_domain_projection_empty_fields_preserves_full_rows_and_counts():
    from hub.agent_context import project

    step = receipt([], projected=True)
    document = json.loads(step.document)
    projection = document["arguments"]["projection"]
    projection["fields"] = []
    rows = [
        {"entity_id": "sensor.unrelated", "state": "12"},
        {
            "entity_id": "update.core",
            "state": "on",
            "attributes": {"installed_version": "1", "latest_version": "2", "in_progress": False},
        },
        {"entity_id": "update.addon", "state": "off"},
    ]
    original = copy.deepcopy(rows)
    body = project(rows, projection)
    step.document = json.dumps(document)
    step.result = json.dumps({"http_status": 200, "body": body})
    snapshot = states_snapshot([step], "ha", "update")
    assert snapshot and snapshot["complete"]
    assert snapshot["pending"] == ["update.core"]
    assert snapshot["current"] == ["update.addon"]
    assert snapshot["entities"][0]["attributes"]["in_progress"] is False
    assert "1 → 2" in summary([step], "ha")
    assert rows == original
    projection["limit"] = 1
    step.document = json.dumps(document)
    step.result = json.dumps({"http_status": 200, "body": project(rows, projection)})
    assert not evidence_satisfied([step], "ha", "update")


def test_other_target_effect_does_not_invalidate_ha_snapshot():
    step = receipt([{"entity_id": "update.core", "state": "off"}])
    other = SimpleNamespace(
        kind="effect",
        status="succeeded",
        sequence=2,
        document=json.dumps({"integration_id": "paperless"}),
    )
    assert evidence_satisfied([step, other], "ha", "update")
    other.document = json.dumps({"integration_id": "ha"})
    assert not evidence_satisfied([step, other], "ha", "update")


def test_mixed_off_unknown_never_states_no_updates():
    step = receipt(
        [
            {"entity_id": "update.core", "state": "off"},
            {"entity_id": "update.addon", "state": "unavailable"},
        ]
    )
    text = summary([step], "ha")
    assert text and "nicht vollständig bestimmen" in text
    assert "kein" not in text.splitlines()[0].casefold()
    assert "kein Status verfügbar" in text
