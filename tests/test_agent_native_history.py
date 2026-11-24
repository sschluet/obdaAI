"""Standard native tool messages retain fitted evidence without supplying authority."""

import hashlib
import json
from copy import deepcopy

import pytest
from hub.agent_context import fit
from hub.agent_native import (
    NativeCallError,
    auxiliary_parts,
    metadata_size,
    native_messages,
    with_history,
)
from test_agent_native import http_binding, prepared


def receipt(sequence=1, *, kind="read", status="succeeded", target="one", path="/api/one/config"):
    return {
        "sequence": sequence,
        "kind": kind,
        "status": status,
        "document": {
            "integration_id": target,
            "tool": "http",
            "arguments": {"method": "GET", "path": path},
        },
        "result": {
            "http_status": 200,
            "body": {"version": "synthetic", "flag": True, "optional": None, "list": [1, False]},
        },
    }


def compiled(history=None, **extra):
    native = prepared()
    fitted = deepcopy(native.data)
    fitted.update(history=history or [receipt()], **extra)
    return native, *with_history(native, fitted)


def rehash(metadata):
    metadata["messages_sha256"] = hashlib.sha256(
        json.dumps(
            metadata["messages"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def test_compiler_creates_standard_pairs_without_mutating_source_or_authority():
    native = prepared()
    history = [receipt(), receipt(2, status="failed")]
    history[1]["result"].update(projection_error="invalid_projection", failure_phase="projection")
    data = {
        **native.data,
        "history": history,
        "latest_observation": {"sequence": 2, "result": "derived"},
        "effect_ledger": [{"sequence": 0, "result_sha256": "a" * 64}],
        "current_state": {"synthetic": True},
    }
    before = deepcopy(data)
    compiled, model_data = with_history(native, data)
    assert data == before
    assert native_messages(native.metadata) == []
    assert compiled.original_data == native.original_data
    assert compiled.original_instruction == native.original_instruction
    assert compiled.metadata["sha256"] == native.metadata["sha256"]
    assert compiled.metadata["tools"] == native.metadata["tools"]
    assert compiled.metadata["bindings"] == native.metadata["bindings"]
    messages = native_messages(compiled.metadata)
    assert [m["role"] for m in messages] == ["assistant", "tool", "assistant", "tool"]
    for index, entry in enumerate(history):
        call = messages[index * 2]["tool_calls"][0]
        assert call["id"] == f"call_obdaai_{entry['sequence']}" and call["type"] == "function"
        assert call["function"]["name"] == http_binding(native)
        assert json.loads(call["function"]["arguments"]) == {
            "arguments": entry["document"]["arguments"]
        }
        observed = json.loads(messages[index * 2 + 1]["content"])
        marker = observed.pop("_obdaai_receipt")
        assert observed == entry["result"]
        assert marker["status"] == entry["status"] and marker["sequence"] == entry["sequence"]
        assert marker["model_view_only"] is True
    assert model_data["history"] == []
    assert model_data["latest_observation"] == {"sequence": 2}
    for key in ["effect_ledger", "current_state", "interfaces", "private_context", "clock"]:
        assert model_data[key] == data[key]
    assert compiled.data == model_data
    messages[0]["tool_calls"][0]["function"]["name"] = "tampered"
    assert native_messages(compiled.metadata)[0]["tool_calls"][0]["function"][
        "name"
    ] == http_binding(native)


@pytest.mark.parametrize(
    "case",
    [
        "prepared",
        "uncertain",
        "verification",
        "model",
        "feedback",
        "foreign",
        "invalid_args",
        "clipped_args",
        "reserved_collision",
    ],
)
def test_unconverted_history_and_latest_observation_are_preserved(case):
    entry = receipt()
    if case in {"prepared", "uncertain"}:
        entry["status"] = case
    elif case in {"verification", "model", "feedback"}:
        entry["kind"] = case
    elif case == "foreign":
        entry["document"]["integration_id"] = "unselected"
    elif case == "invalid_args":
        entry["document"]["arguments"]["path"] = "/api/two/foreign"
    elif case == "clipped_args":
        entry["document"]["arguments"] = {"content_omitted": True, "full_sha256": "a" * 64}
    else:
        entry["result"]["_obdaai_receipt"] = {"injected": True}
    native, result, model_data = compiled([entry], latest_observation={"sequence": 1})
    assert native_messages(result.metadata) == []
    assert model_data["history"] == [entry] and model_data["latest_observation"] == {"sequence": 1}
    assert result.metadata == native.metadata


def test_only_convertible_entries_removed_and_effect_ledger_stays():
    failed = receipt(1, status="failed")
    feedback = {
        "sequence": 2,
        "kind": "feedback",
        "status": "succeeded",
        "document": {"instruction": "Synthetic feedback"},
        "result": {},
    }
    effect = receipt(3, kind="effect")
    effect["document"]["arguments"] = {
        "method": "POST",
        "path": "/api/one/update",
        "body": {"enable": True},
    }
    effect["result"] = {"http_status": 200, "effect_verified": True, "body": {"success": True}}
    _, result, data = compiled(
        [failed, feedback, effect],
        effect_ledger=[{"kept": True}],
        latest_observation={"sequence": 3},
    )
    assert data["history"] == [feedback] and data["effect_ledger"] == [{"kept": True}]
    messages = native_messages(result.metadata)
    assert len(messages) == 4
    assert json.loads(messages[-1]["content"])["effect_verified"] is True
    assert json.loads(messages[-1]["content"])["_obdaai_receipt"]["kind"] == "effect"


def test_auxiliary_history_exact_local_bytes_and_hash():
    _, result, _ = compiled()
    parts = auxiliary_parts(result.metadata)
    assert [p.source_id for p in parts] == ["agent-native-tools", "agent-native-history"]
    assert all(str(p.label) == "LOCAL_ONLY" for p in parts)
    assert json.loads(parts[1].content) == native_messages(result.metadata)
    assert metadata_size(result.metadata) == (
        sum(len(p.content) for p in parts),
        sum(len(p.content.encode()) for p in parts),
    )
    assert (
        result.metadata["messages_sha256"] == hashlib.sha256(parts[1].content.encode()).hexdigest()
    )


@pytest.mark.parametrize(
    "case",
    [
        "hash",
        "name",
        "args",
        "orphan",
        "mismatch",
        "duplicate",
        "role",
        "assistant_text",
        "receipt",
        "multi",
        "missing_hash",
    ],
)
def test_message_validation_rejects_tampering_even_with_recomputed_history_hash(case):
    _, result, _ = compiled()
    metadata = deepcopy(result.metadata)
    messages = metadata["messages"]
    if case == "hash":
        metadata["messages_sha256"] = "0" * 64
    elif case == "missing_hash":
        metadata.pop("messages_sha256")
    else:
        if case == "name":
            messages[0]["tool_calls"][0]["function"]["name"] = "SYNTHETIC_PRIVATE_UNKNOWN"
        elif case == "args":
            messages[0]["tool_calls"][0]["function"]["arguments"] = json.dumps(
                {"arguments": {"method": "POST", "path": "/api/foreign", "body": {"private": True}}}
            )
        elif case == "orphan":
            metadata["messages"] = messages[:1]
        elif case == "mismatch":
            messages[1]["tool_call_id"] = "call_obdaai_2"
        elif case == "duplicate":
            messages.extend(deepcopy(messages))
        elif case == "role":
            messages[1]["role"] = "system"
        elif case == "assistant_text":
            messages[0]["content"] = "SYNTHETIC_PRIVATE_POLICY"
        elif case == "receipt":
            content = json.loads(messages[1]["content"])
            content["_obdaai_receipt"]["integration_id"] = "foreign"
            messages[1]["content"] = json.dumps(content)
        else:
            messages[0]["tool_calls"].append(deepcopy(messages[0]["tool_calls"][0]))
        rehash(metadata)
    with pytest.raises(NativeCallError) as caught:
        native_messages(metadata)
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + str(caught.value.issues)


def test_duplicate_or_out_of_order_sequences_are_not_represented_as_new_native_calls():
    _, result, data = compiled([receipt(1), receipt(1)])
    assert native_messages(result.metadata) == [] and len(data["history"]) == 2
    _, result, data = compiled([receipt(2), receipt(1)])
    assert len(native_messages(result.metadata)) == 2
    assert [item["sequence"] for item in data["history"]] == [1]


def test_recompile_replaces_history_not_accumulates_and_uses_fitted_result_only():
    native = prepared()
    entry = receipt()
    entry["result"]["body"]["large"] = "界" * 12000
    data = {**native.data, "history": [entry]}
    fitted = fit(data, native.instruction, 18000)
    result, model_data = with_history(native, fitted)
    observed = json.loads(native_messages(result.metadata)[1]["content"])
    observed.pop("_obdaai_receipt")
    assert observed == fitted["history"][0]["result"]
    assert "界" * 12000 not in json.dumps(result.metadata, ensure_ascii=False)
    newer = {**native.data, "history": [receipt(2)]}
    rebuilt, _ = with_history(result, newer)
    assert len(native_messages(rebuilt.metadata)) == 2
    assert native_messages(rebuilt.metadata)[0]["tool_calls"][0]["id"] == "call_obdaai_2"
    assert model_data["history"] == []


@pytest.mark.parametrize("bad", [None, "not-a-list", {"private": "value"}, [None]])
def test_malformed_history_raises_only_safe_protocol_error(bad):
    native = prepared()
    metadata = deepcopy(native.metadata)
    metadata["messages"] = bad
    rehash(metadata)
    with pytest.raises(NativeCallError) as caught:
        native_messages(metadata)
    assert "private" not in str(caught.value) + str(caught.value.issues)


def test_clipped_argument_document_is_retained_in_base_view():
    native = prepared()
    entry = receipt()
    entry["document"] = {
        "excerpt": "synthetic clipped document",
        "truncated": True,
        "full_sha256": "a" * 64,
    }
    data = {**native.data, "history": [entry], "latest_observation": {"sequence": 1}}
    compiled, model_data = with_history(native, data)
    assert native_messages(compiled.metadata) == []
    assert model_data == data


def test_large_array_latest_semantic_summary_survives_without_duplicate_result():
    entry = receipt()
    entry["document"]["arguments"]["path"] = "/api/one/states"
    entry["result"]["body"] = [
        {
            "entity_id": "light.synthetic_" + str(i),
            "state": "on",
            "attributes": {"friendly_name": "Synthetic light " + str(i), "note": "界" * 100},
        }
        for i in range(150)
    ]
    native = prepared(history=[entry])
    fitted = fit(native.data, native.instruction, 18000)
    latest = fitted["latest_observation"]
    semantic = latest["summary"]["semantic_view"]
    assert semantic["observed_count"] == 150
    assert semantic["observed_domain_counts"] == {"light": 150}
    compiled, model_data = with_history(native, fitted)
    assert model_data["history"] == []
    assert model_data["latest_observation"] == {
        key: value for key, value in latest.items() if key != "result"
    }
    assert model_data["latest_observation"]["summary"]["semantic_view"] == semantic
    assert model_data["latest_observation"]["full_sha256"] == latest["full_sha256"]
    assert "result" not in model_data["latest_observation"]
    messages = native_messages(compiled.metadata)
    assert len(messages) == 2
    observation = json.loads(messages[1]["content"])
    observation.pop("_obdaai_receipt")
    assert observation == fitted["history"][0]["result"]
