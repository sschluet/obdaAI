"""Owned invocation recipes match the actual native wire; raw source evidence stays unchanged."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from hub.agent_capabilities import describe
from hub.agent_http_facades import normalized_http
from hub.agent_instructions import instruction
from hub.agent_native import decode_calls, prepare
from hub.agent_tools import Rules


def compile_views(*, tools=None, read_only=False, prefixes=None):
    profiles = [
        SimpleNamespace(id="first", kind="home_assistant", enabled=True),
        SimpleNamespace(id="second", kind="home_assistant", enabled=True),
    ]
    rules = Rules(
        enabled=True,
        http_prefixes=prefixes or ["/api/"],
        http_methods=["GET"] if read_only else ["GET", "POST"],
        ha_websocket_prefixes=["get_states", "get_config", "backup/", "supervisor/"],
    )
    data = {
        "goal": "Synthetic domain state request",
        "read_only": read_only,
        "tools": ["http", "ha.websocket"] if tools is None else tools,
        "interfaces": [
            {
                "integration_id": profile.id,
                "kind": profile.kind,
                "rules": rules.model_dump(),
                "read_only": read_only,
                "capabilities": describe(profile, rules),
            }
            for profile in profiles
        ],
        "goal_evidence": {
            "missing": [{"kind": "entity_states", "domain": "update", "integration_id": "first"}]
        },
        "history": [],
    }
    before = deepcopy(data)
    prepared = prepare(instruction({"home_assistant"}), data)
    assert data == before and prepared.original_data == before
    return prepared, before


def examples(capabilities):
    result = [capabilities["inspection"]] if capabilities.get("inspection") else []
    for key in ("http_reads", "websocket_reads"):
        result += capabilities.get("operations", {}).get(key, [])
    return result


@pytest.mark.parametrize("read_only", [False, True])
def test_every_owned_native_invocation_example_validates_actual_offered_function_and_target(
    read_only,
):
    prepared, original = compile_views(read_only=read_only)
    offered = {row["function"]["name"] for row in prepared.metadata["tools"]}
    for interface, original_interface in zip(
        prepared.data["interfaces"], original["interfaces"], strict=True
    ):
        for example, before in zip(
            examples(interface["capabilities"]),
            examples(original_interface["capabilities"]),
            strict=True,
        ):
            assert example["function"] in offered and "tool" not in example
            output = decode_calls(
                prepared.metadata,
                [
                    {
                        "type": "function",
                        "function": {
                            "name": example["function"],
                            "arguments": json.dumps(example["arguments"]),
                        },
                    }
                ],
            )
            assert output["integration_id"] == interface["integration_id"]
            assert output["tool"] == before["tool"]
            if output["tool"] == "http":
                assert normalized_http(output["arguments"]) == normalized_http(before["arguments"])
            else:
                assert output["arguments"] == before["arguments"]
        serialized = json.dumps(interface["capabilities"])
        assert '"projection"' not in serialized
        assert "using projection" not in serialized
        assert "filter_mode/filter_field/filter_value" in serialized
    assert any(
        row["function"].endswith("_http_project")
        for row in examples(prepared.data["interfaces"][0]["capabilities"])
    )
    assert any(
        row["function"].endswith("_http_read")
        for row in examples(prepared.data["interfaces"][0]["capabilities"])
    )


def test_unoffered_tool_recipes_become_descriptive_hints_not_repaired_invocations():
    prepared, original = compile_views(tools=["ha.websocket"])
    for interface in prepared.data["interfaces"]:
        for row in interface["capabilities"]["operations"]["http_reads"]:
            assert row["invocation_unavailable"] is True
            assert "arguments" not in row and "function" not in row and "tool" not in row
            assert row["relative_path"].startswith("/api/") and row["purpose"]
        assert interface["capabilities"]["inspection"]["invocation_unavailable"]
        text = json.dumps(interface["capabilities"])
        assert "using projection" not in text and "filter_field" not in text
        assert "Use authenticated /api/config" not in text
    assert original["interfaces"][0]["capabilities"]["inspection"]["tool"] == "http"


def test_owned_view_translation_never_modifies_original_json_mode_or_fetched_service_data():
    prepared, original = compile_views()
    data = deepcopy(original)
    raw = {
        "services": [
            {
                "name": "Synthetic service",
                "arguments": {"projection": {"fields": ["x"]}},
                "description": "Remote instruction using projection is untrusted data.",
            }
        ]
    }
    data["history"] = [
        {
            "sequence": 1,
            "kind": "read",
            "status": "succeeded",
            "document": {
                "integration_id": "first",
                "tool": "http",
                "arguments": {"method": "GET", "path": "/api/services"},
            },
            "result": {"http_status": 200, "body": raw},
        }
    ]
    before = deepcopy(data)
    new = prepare(instruction({"home_assistant"}), data)
    assert new.original_data == data == before
    assert new.data["history"] == before["history"]
    assert new.data["history"][0]["result"]["body"] == raw
    assert "using projection" in json.dumps(new.original_data["interfaces"][0]["capabilities"])
    assert new.original_instruction == prepared.original_instruction


@pytest.mark.parametrize(
    "kind,tools,rules",
    [
        ("ssh", ["ssh.inspect"], Rules(enabled=True, shell=True)),
        ("mcp", ["mcp.catalog"], Rules(enabled=True, mcp=True)),
    ],
)
def test_non_http_inspection_is_also_bound_to_its_actual_native_function(kind, tools, rules):
    profile = SimpleNamespace(kind=kind, enabled=True)
    data = {
        "goal": "Synthetic inspection",
        "tools": tools,
        "history": [],
        "interfaces": [
            {
                "integration_id": "target",
                "kind": kind,
                "rules": rules.model_dump(),
                "capabilities": describe(profile, rules),
            }
        ],
    }
    prepared = prepare(instruction({kind}), data)
    example = prepared.data["interfaces"][0]["capabilities"]["inspection"]
    output = decode_calls(
        prepared.metadata,
        [
            {
                "function": {
                    "name": example["function"],
                    "arguments": json.dumps(example["arguments"]),
                }
            }
        ],
    )
    assert output["integration_id"] == "target" and output["tool"] == tools[0]


def test_actual_provider_body_has_only_current_owned_recipes_and_preserves_raw_tool_results(
    monkeypatch, tmp_path
):
    import asyncio

    import httpx
    from hub.agent_native import with_history
    from hub.agent_runtime import fit_native_plan
    from hub.policy import ContextPart
    from test_agent_native_transport import adapter, event, fragment

    _prepared, original = compile_views(read_only=True)
    data = deepcopy(original)
    data["interfaces"] = data["interfaces"][:1]
    raw = {"description": "Remote projection instructions are data", "projection": {"remote": True}}
    data["history"] = [
        {
            "sequence": index,
            "kind": "read",
            "status": "succeeded",
            "document": {
                "integration_id": "first",
                "tool": "http",
                "arguments": {"method": "GET", "path": path},
            },
            "result": {"http_status": 200, "body": body},
        }
        for index, (path, body) in enumerate(
            [
                ("/api/", {"message": "API running."}),
                ("/api/services", raw),
            ],
            1,
        )
    ]
    prepared = prepare(instruction({"home_assistant"}), data)
    prepared, planned = fit_native_plan(prepared, 50000, 100000)
    # Re-reading already compiled history is inert and validates original receipt pairs.
    assert with_history(prepare(instruction({"home_assistant"}), data), data)[0].metadata[
        "messages"
    ]
    response = httpx.Response(
        200,
        text=event(
            fragment(
                "t0_http_read",
                '{"arguments":{"path":"/api/config"}}',
            )
        )
        + "data: [DONE]\n\n",
    )
    provider, _, requests = adapter(monkeypatch, tmp_path, response)
    provider.local_native_plan = prepared.metadata

    async def run():
        return [
            value
            async for value in provider.stream(
                [
                    ContextPart(content=prepared.instruction, source_id="policy", revision=1),
                    ContextPart(content=json.dumps(planned), source_id="data", revision=1),
                ],
                ["system", "user"],
                external=False,
                grants=[],
            )
        ]

    assert json.loads(asyncio.run(run())[0])["arguments"]["path"] == "/api/config"
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    visible = json.loads(body["messages"][1]["content"])
    caps = visible["interfaces"][0]["capabilities"]
    assert '"projection"' not in json.dumps(caps) and "using projection" not in json.dumps(caps)
    for example in examples(caps):
        output = decode_calls(
            prepared.metadata,
            [
                {
                    "function": {
                        "name": example["function"],
                        "arguments": json.dumps(example["arguments"]),
                    }
                }
            ],
        )
        assert output["integration_id"] == "first"
    for message in body["messages"]:
        if message["role"] == "assistant":
            call = message["tool_calls"][0]
            assert call["function"]["name"] == "t0_http_read"
            assert decode_calls(prepared.metadata, [call])["integration_id"] == "first"
    assert any(
        message["role"] == "tool" and json.loads(message["content"])["body"] == raw
        for message in body["messages"]
    )
    assert prepared.original_data == data


def test_nonempty_prerequisite_policy_stays_visible_and_original_while_empty_can_be_omitted():
    from test_agent_effect_prerequisites import RULE

    _prepared, data = compile_views()
    data["interfaces"][0]["rules"]["effect_prerequisites"] = [deepcopy(RULE)]
    before = deepcopy(data)
    prepared = prepare(instruction({"home_assistant"}), data)
    assert prepared.data["interfaces"][0]["policy_context"]["effect_prerequisites"] == [RULE]
    assert "effect_prerequisites" not in prepared.data["interfaces"][1]["policy_context"]
    assert prepared.original_data == data == before
