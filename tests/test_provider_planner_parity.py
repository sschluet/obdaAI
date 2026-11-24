"""Planner diagnostic uses the real bounded native context without target dispatch."""

import json

import pytest
from test_provider_native_planner import intent, launch, native, sse, transport

pytest_plugins = ["test_provider_settings"]


@pytest.mark.parametrize("include_connection", [False, True])
def test_probe_uses_goal_evidence_alias_and_original_bootstrap_native_pair(
    managed, monkeypatch, include_connection
):
    import hub.agent_tools as tools

    monkeypatch.setattr(tools, "invoke", lambda *a, **kw: pytest.fail("No target dispatch"))
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            value = intent()
            if include_connection:
                value["requirements"].append(
                    {"kind": "connection", "integration_id": "synthetic-ha", "domain": ""}
                )
            return sse({"content": json.dumps(value)})
        assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "tool"]
        data = json.loads(body["messages"][1]["content"])
        assert not data["goal_evidence"]["satisfied"]
        assert data["goal_evidence"]["missing"] == [
            {"kind": "entity_states", "domain": "light", "integration_id": "synthetic-ha"}
        ]
        assert data["remaining_effects"] == 0 and not data["allow_finish"]
        assistant, result = body["messages"][2:]
        call = assistant["tool_calls"][0]
        assert call["function"]["name"] == "t0_http"
        assert result["tool_call_id"] == call["id"] == "call_obdaai_1"
        arguments = json.loads(call["function"]["arguments"])["arguments"]
        assert arguments == {"method": "GET", "path": "/api/"}
        receipt = json.loads(result["content"])
        assert receipt["http_status"] == 200 and receipt["_obdaai_receipt"]["sequence"] == 1
        assert [t["function"]["name"] for t in body["tools"]] == ["t0_ha_entities", "t0_http"]
        return sse(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "synthetic-alias",
                        "type": "function",
                        "function": {
                            "name": "t0_ha_entities",
                            "arguments": '{"arguments":{"domain":"light"}}',
                        },
                    }
                ]
            }
        )

    transport(monkeypatch, handler)
    result = launch(managed)
    assert result["status"] == "succeeded" and result["provenance"]["native_pass"]
    assert not result["provenance"]["compatibility_used"] and len(calls) == 2
    assert "failure_category" not in result["provenance"]


@pytest.mark.parametrize(
    "phase, failure, category",
    [
        ("json_intent", "json", "invalid_json"),
        ("native", "wrong_target", "selection_mismatch"),
        ("native", "unknown_function", "native_arguments_invalid"),
        ("json_compatibility", "json", "invalid_json"),
        ("json_compatibility", "wrong_target", "selection_mismatch"),
    ],
)
def test_safe_failure_stage_and_category_never_output_error_or_model_text(
    managed, monkeypatch, phase, failure, category
):
    calls = []
    secret = "SYNTHETIC_PRIVATE_MODEL_ERROR_SECRET"

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        stage = (
            "json_intent"
            if len(calls) == 1
            else ("native" if len(calls) == 2 else "json_compatibility")
        )
        if stage != phase:
            if stage == "json_intent":
                return sse({"content": json.dumps(intent())})
            assert stage == "native"
            return sse({"content": secret})  # completed no-selection, one allowed compatibility
        if failure == "json":
            return sse({"content": secret})
        if stage == "native":
            return (
                native(path="/api/config")
                if failure == "wrong_target"
                else native(name="foreign_" + secret)
            )
        return sse(
            {
                "content": json.dumps(
                    {
                        "kind": "tool",
                        "tool": "http",
                        "integration_id": secret,
                        "arguments": {"method": "GET", "path": "/api/states"},
                    }
                )
            }
        )

    transport(monkeypatch, handler)
    result = launch(managed)
    assert result["status"] == "failed"
    assert result["provenance"]["failure_stage"] == phase
    assert result["provenance"]["failure_category"] == category
    assert secret not in json.dumps(result)
    assert len(calls) == {"json_intent": 1, "native": 2, "json_compatibility": 3}[phase]
