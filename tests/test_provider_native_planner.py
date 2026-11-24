"""Native probe exercises the production compiler/decoder, never target dispatch."""

import json
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from hub.db import ProviderConfig, ProviderTest

pytest_plugins = ["test_provider_settings"]


def intent():
    return {
        "target_ids": ["synthetic-ha"],
        "mode": "observe",
        "topic": "inventory",
        "answer_kind": "general",
        "research": False,
        "followup": False,
        "freshness": "current",
        "confidence": "certain",
        "requirements": [
            {"kind": "entity_states", "integration_id": "synthetic-ha", "domain": "light"}
        ],
    }


def sse(delta, *, done=True):
    return httpx.Response(
        200,
        text="data: "
        + json.dumps({"choices": [{"delta": delta}]})
        + ("\n\ndata: [DONE]\n\n" if done else "\n\n"),
    )


def native(*, name="t0_http", path="/api/states"):
    # Real SSE fragments are reassembled by Providers before the bound decoder.
    args = json.dumps({"method": "GET", "path": path})
    chunks = [
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "synthetic",
                    "type": "function",
                    "function": {"name": name[:3], "arguments": args[:8]},
                }
            ]
        },
        {"tool_calls": [{"index": 0, "function": {"name": name[3:], "arguments": args[8:]}}]},
    ]
    return httpx.Response(
        200,
        text="".join("data: " + json.dumps({"choices": [{"delta": d}]}) + "\n\n" for d in chunks)
        + "data: [DONE]\n\n",
    )


def launch(managed):
    _, client, headers, _ = managed
    identifier = str(uuid4())
    assert (
        client.post(
            "/api/providers/local-default/test",
            headers=headers,
            json={"mode": "planner", "request_id": identifier},
        ).status_code
        == 200
    )
    for _ in range(200):
        result = client.get("/api/provider-tests/" + identifier).json()
        if result["status"] not in {"queued", "running"}:
            return result
        time.sleep(0.01)
    pytest.fail("Probe did not settle")


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )


def test_native_probe_real_fragment_decoder_and_provider_rows_preserved(managed, monkeypatch):
    app, client, _, _ = managed
    with app.state.sessions() as db:
        row = db.get(ProviderConfig, "local-default")
        original = (row.config, row.revision, row.is_default, row.encrypted_secret)
    calls = []

    def handler(request):
        from sqlalchemy import select

        with app.state.sessions() as db:
            pending = db.scalar(select(ProviderTest).where(ProviderTest.status == "running"))
            durable = json.loads(pending.result)["provenance"]
            assert durable["attempts"][-1]["status"] == "running"
            assert durable["attempts"][-1]["protocol"] == ("json_intent" if not calls else "native")
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            assert "response_format" in body and "tools" not in body
            return sse({"content": json.dumps(intent())})
        assert "response_format" not in body and body["tool_choice"] == "auto"
        assert [t["function"]["name"] for t in body["tools"]] == ["t0_ha_entities", "t0_http"]
        assert body["tools"][0]["function"]["parameters"]
        return native()

    transport(monkeypatch, handler)
    result = launch(managed)
    assert result["status"] == "succeeded"
    proof = result["provenance"]
    assert proof["native_pass"] and not proof["compatibility_pass"]
    assert not proof["compatibility_used"] and proof["selection_protocol"] == "native"
    assert proof["attempts"] == [
        {"protocol": "json_intent", "status": "succeeded"},
        {"protocol": "native", "status": "succeeded"},
    ]
    with app.state.sessions() as db:
        row = db.get(ProviderConfig, "local-default")
        assert (row.config, row.revision, row.is_default, row.encrypted_secret) == original
    last = next(
        p for p in client.get("/api/providers").json()["providers"] if p["id"] == "local-default"
    )["last_test"]
    assert last["provenance"] == proof and isinstance(last["result"], str)
    assert len(calls) == 2


@pytest.mark.parametrize("reason", ["unsupported", "no_selection"])
def test_compatibility_is_separate_single_attempt_not_native_pass(managed, monkeypatch, reason):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return sse({"content": json.dumps(intent())})
        if len(calls) == 2:
            assert "tools" in body
            if reason == "unsupported":
                return httpx.Response(
                    422, json={"error": {"code": "unsupported_parameter", "param": "tools"}}
                )
            return sse({"content": "Choose no tool."})
        assert len(calls) == 3 and "tools" not in body and "response_format" in body
        return sse(
            {
                "content": json.dumps(
                    {
                        "kind": "tool",
                        "integration_id": "synthetic-ha",
                        "tool": "http",
                        "message": "Read states",
                        "arguments": {"method": "GET", "path": "/api/states"},
                    }
                )
            }
        )

    transport(monkeypatch, handler)
    result = launch(managed)
    assert result["status"] == "succeeded"
    proof = result["provenance"]
    assert not proof["native_pass"] and proof["compatibility_pass"]
    assert proof["compatibility_used"] and proof["selection_protocol"] == "json_compatibility"
    assert len(proof["attempts"]) == 3 and len(calls) == 3
    assert proof["attempts"][1]["status"] == reason
    assert "nativ nicht belegt" in result["result"]


@pytest.mark.parametrize("failure", ["auth", "timeout", "invalid", "truncated", "generic422"])
def test_no_compatibility_after_other_failures(managed, monkeypatch, failure):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return sse({"content": json.dumps(intent())})
        assert len(calls) == 2
        if failure == "auth":
            return httpx.Response(401, text="SYNTHETIC_PRIVATE_ERROR_TOKEN")
        if failure == "timeout":
            raise httpx.ReadTimeout("SYNTHETIC_PRIVATE_ERROR_TOKEN")
        if failure == "invalid":
            return native(name="foreign_target")
        if failure == "generic422":
            return httpx.Response(422, json={"error": {"message": "unrelated validation"}})
        return sse(
            {
                "tool_calls": [
                    {"index": 0, "function": {"name": "t0_http", "arguments": '{"method":"GET"'}}
                ]
            },
            done=False,
        )

    transport(monkeypatch, handler)
    result = launch(managed)
    assert result["status"] == "failed" and len(calls) == 2
    assert not result["provenance"]["compatibility_used"]
    assert not result["provenance"]["native_pass"]
    assert result["provenance"]["failure_stage"] == "native"
    expected_category = {
        "auth": "authentication_failed",
        "timeout": "timeout",
        "invalid": "native_arguments_invalid",
        "truncated": "validation_error",
        "generic422": "http_error",
    }[failure]
    assert result["provenance"]["failure_category"] == expected_category
    assert "SYNTHETIC_PRIVATE_ERROR_TOKEN" not in json.dumps(result)


@pytest.mark.parametrize("change", ["revision", "disabled", "interrupted"])
def test_native_queue_boundary_rechecks_provider_and_probe(managed, monkeypatch, change):
    import hub.providers as providers

    app, _, _, _ = managed
    calls, slots = [], []

    @asynccontextmanager
    async def capacity(*args):
        slots.append(True)
        if len(slots) == 2:
            with app.state.sessions() as db:
                row = db.get(ProviderConfig, "local-default")
                if change == "revision":
                    row.revision += 1
                elif change == "disabled":
                    row.enabled = False
                else:
                    from sqlalchemy import select

                    probe = db.scalar(select(ProviderTest).where(ProviderTest.status == "running"))
                    probe.status = "interrupted"
                db.commit()
        yield

    def handler(request):
        calls.append(True)
        assert len(calls) == 1
        return sse({"content": json.dumps(intent())})

    monkeypatch.setattr(providers, "local_capacity", capacity)
    transport(monkeypatch, handler)
    result = launch(managed)
    assert result["status"] == ("interrupted" if change == "interrupted" else "failed")
    assert len(calls) == 1 and len(slots) == 2
    assert not result["provenance"]["compatibility_used"]


def test_native_tool_auxiliary_bytes_cannot_escape_probe_budget(managed, monkeypatch):
    import hub.agent_native as compiler
    from hub.agent_native import PreparedNative

    original_prepare = compiler.prepare
    calls = []

    def oversized(*args):
        value = original_prepare(*args)
        metadata = json.loads(json.dumps(value.metadata))
        # Model metadata is all LOCAL_ONLY; even non-message schema bytes count.
        metadata["tools"][0]["function"]["description"] = "界" * 40000
        return PreparedNative(
            value.instruction, value.data, metadata, value.original_instruction, value.original_data
        )

    def handler(request):
        calls.append(True)
        assert len(calls) == 1
        return sse({"content": json.dumps(intent())})

    monkeypatch.setattr(compiler, "prepare", oversized)
    transport(monkeypatch, handler)
    result = launch(managed)
    assert result["status"] == "failed" and len(calls) == 1
    assert not result["provenance"]["compatibility_used"]


def test_planner_cannot_override_local_privacy_allowlist(managed, monkeypatch):
    app, _, _, _ = managed
    with app.state.sessions() as db:
        row = db.get(ProviderConfig, "local-default")
        config = json.loads(row.config)
        config["allowed_labels"] = ["CLOUD_ALLOWED"]
        row.config = json.dumps(config)
        db.commit()

    def handler(request):
        pytest.fail("LOCAL_ONLY planner probe must not leave disallowed provider")

    transport(monkeypatch, handler)
    result = launch(managed)
    assert result["status"] == "failed"
    assert not result["provenance"]["native_pass"]
    assert not result["provenance"]["compatibility_used"]
