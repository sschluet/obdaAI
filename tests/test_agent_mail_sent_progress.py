"""Synthetic observed-folder choices, zero-result attempts and safe terminal cases."""

import json

import pytest
from hub import agent_mail_cohort as cohort
from hub import agent_mail_sent_progress as progress
from hub.action_api import digest, encode
from hub.agent_models import AgentStep
from hub.mcp_client import schema_digest
from test_agent_mail_cohort import context as cohort_context  # noqa: F401
from test_agent_mail_cohort import freeze, row
from test_agent_read_references import receipt  # noqa: F401


@pytest.fixture
def sent_context(cohort_context):  # noqa: F811
    ctx = cohort_context
    schemas = {
        "list_folders": {"type": "object", "properties": {}, "additionalProperties": False},
        "list_emails": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "default": "INBOX"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                "since_days": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None},
                "unread_only": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        "search_emails": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
                "folder": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    }
    rules = ctx[-1][ctx[5].id][1]
    for name, schema in schemas.items():
        rules.mcp_read_tools[name] = schema_digest(schema)
    ctx[6].rules = rules.model_dump_json()
    document = json.loads(ctx[4].document)
    document["arguments"]["schema_sha256"] = schema_digest(schemas["search_emails"])
    ctx[4].document = encode(document)
    ctx[4].sha256 = digest(ctx[4].document)
    freeze(ctx, [row(1, answered=True), row(2, answered=False)])
    return ctx, schemas


def contracts(fixture):
    ctx, schemas = fixture
    return {
        "interfaces": [
            {
                "integration_id": ctx[5].id,
                "tools": [
                    {"name": name, "schema_sha256": schema_digest(schema)}
                    for name, schema in schemas.items()
                ],
            }
        ],
        "schemas": {schema_digest(schema): schema for schema in schemas.values()},
    }


def step(fixture, name, payload, sequence=1, args=None):
    ctx, schemas = fixture
    document = json.loads(ctx[4].document)
    document["arguments"] = {
        "name": name,
        "schema_sha256": schema_digest(schemas[name]),
        "arguments": args or {},
    }
    return AgentStep(
        job_id=ctx[1].id,
        sequence=sequence,
        kind="read",
        status="succeeded",
        document=encode(document),
        sha256=digest(encode(document)),
        result=encode({"response": {"content": [encode(payload)]}}),
    )


def folders(fixture, **updates):
    return step(
        fixture,
        "list_folders",
        [{"name": "Actual Sent", "flags": ["\\Sent"], "selectable": True, **updates}],
    )


def call(fixture, history=None, observed=None):
    ctx, _ = fixture
    return progress.sent_ready_reads(
        ctx[0],
        ctx[1],
        ctx[-1],
        history or [],
        contracts(fixture) if observed is None else observed,
    )


def evidence(fixture, history):
    ctx, _ = fixture
    return cohort.cohort_evidence(ctx[0], ctx[1], ctx[-1], history)


def test_first_discover_actual_folder_without_guessing(sent_context):
    result = call(sent_context)
    decision = result["decisions"][0]
    assert decision["arguments"]["name"] == "list_folders"
    assert decision["arguments"]["arguments"] == {}
    assert len(encode(result).encode()) <= 1800


def test_next_query_uses_observed_folder_and_bounded_limit(sent_context):
    result = call(sent_context, [folders(sent_context)])
    args = result["decisions"][0]["arguments"]
    assert args["name"] == "list_emails"
    assert args["arguments"] == {"folder": "Actual Sent", "limit": 20}


def test_search_fallback_is_empty_query_not_generated_search(sent_context):
    observed = contracts(sent_context)
    observed["interfaces"][0]["tools"] = [
        t for t in observed["interfaces"][0]["tools"] if t["name"] != "list_emails"
    ]
    result = call(sent_context, [folders(sent_context)], observed)
    assert result["decisions"][0]["arguments"]["arguments"] == {
        "folder": "Actual Sent",
        "limit": 20,
        "query": "",
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [{"name": "Not sent", "flags": [], "selectable": True}],
        [{"name": "Actual Sent", "flags": ["\\Sent"], "selectable": False}],
    ],
)
def test_successful_discovery_without_selectable_sent_is_terminal(sent_context, payload):
    discovery = step(sent_context, "list_folders", payload)
    assert call(sent_context, [discovery])["decisions"] == []
    assert evidence(sent_context, [discovery])["sent_discovery_observed"] is True
    assert evidence(sent_context, [discovery])["sent_query_observed"] is False


def test_empty_sent_query_counts_attempt_never_negative_or_complete(sent_context):
    discovery = folders(sent_context)
    query = step(
        sent_context,
        "list_emails",
        {"folder": "Actual Sent", "messages": []},
        2,
        {"folder": "Actual Sent", "limit": 20},
    )
    result = evidence(sent_context, [discovery, query])
    assert result["sent_query_observed"] is True
    assert result["sent_coverage_complete"] is False
    assert all(r[3] is None for r in result["rows"])
    assert call(sent_context, [discovery, query])["decisions"] == []


@pytest.mark.parametrize(
    "variant",
    [
        "wrong_folder",
        "before_discovery",
        "failed",
        "wrong_account",
        "tampered",
        "payload_folder_mismatch",
    ],
)
def test_invalid_query_does_not_establish_attempt(sent_context, variant):
    discovery = folders(sent_context)
    query = step(
        sent_context,
        "list_emails",
        {"folder": "Actual Sent", "messages": []},
        2,
        {"folder": "Actual Sent", "limit": 20},
    )
    if variant == "wrong_folder":
        query = step(
            sent_context, "list_emails", {"messages": []}, 2, {"folder": "INBOX", "limit": 20}
        )
    elif variant == "before_discovery":
        query.sequence, discovery.sequence = 1, 2
    elif variant == "failed":
        query.status = "failed"
    elif variant == "wrong_account":
        document = json.loads(query.document)
        document["integration_id"] = "other"
        query.document, query.sha256 = encode(document), digest(encode(document))
    elif variant == "tampered":
        query.sha256 = "0" * 64
    else:
        query.result = encode(
            {"response": {"content": [encode({"folder": "INBOX", "messages": []})]}}
        )
    assert evidence(sent_context, [discovery, query])["sent_query_observed"] is False


@pytest.mark.parametrize(
    "variant",
    [
        "missing_catalog",
        "schema_hash",
        "unseen",
        "unknown_fields",
        "unknown_required",
        "effect_only",
    ],
)
def test_unsupported_schema_or_rights_yields_no_choice(sent_context, variant):
    ctx, schemas = sent_context
    observed = contracts(sent_context)
    if variant == "missing_catalog":
        observed = {}
    elif variant == "schema_hash":
        observed["schemas"][schema_digest(schemas["list_folders"])] = {"type": "string"}
    elif variant == "unseen":
        observed["interfaces"] = []
    elif variant in {"unknown_fields", "unknown_required"}:
        schema = schemas["list_folders"]
        schema["properties"] = {"code": {"type": "string", "default": "execute me"}}
        if variant == "unknown_required":
            schema["required"] = ["code"]
        rules = ctx[-1][ctx[5].id][1]
        rules.mcp_read_tools["list_folders"] = schema_digest(schema)
        ctx[6].rules = rules.model_dump_json()
        observed = contracts(sent_context)
    else:
        rules = ctx[-1][ctx[5].id][1]
        rules.mcp_read_tools.pop("list_folders")
        rules.mcp = True
        ctx[6].rules = rules.model_dump_json()
    assert call(sent_context, observed=observed)["decisions"] == []


def test_revocation_stops_planning(sent_context):
    sent_context[0][5].enabled = False
    with pytest.raises(PermissionError):
        call(sent_context)


def test_failed_discovery_does_not_retry(sent_context):
    discovery = folders(sent_context)
    discovery.status = "failed"
    assert call(sent_context, [discovery])["decisions"] == []


def test_failed_sent_query_does_not_retry_or_fallback(sent_context):
    discovery = folders(sent_context)
    query = step(sent_context, "list_emails", {}, 2, {"folder": "Actual Sent", "limit": 20})
    query.status = "failed"
    assert call(sent_context, [discovery, query])["decisions"] == []


def test_thread_in_all_mail_never_counts_as_sent_query(sent_context):
    ctx, schemas = sent_context
    schemas["get_thread"] = {"type": "object", "properties": {}}
    rules = ctx[-1][ctx[5].id][1]
    rules.mcp_read_tools["get_thread"] = schema_digest(schemas["get_thread"])
    ctx[6].rules = rules.model_dump_json()
    thread = step(
        sent_context,
        "get_thread",
        [row(99, folder="All Mail", in_reply_to="<1@synthetic.invalid>")],
        2,
    )
    result = evidence(sent_context, [folders(sent_context), thread])
    assert result["sent_query_observed"] is False
    assert all(r[3] is None for r in result["rows"])


def test_successful_sent_query_records_positive_exact_edge(sent_context):
    query = step(
        sent_context,
        "list_emails",
        {
            "folder": "Actual Sent",
            "messages": [row(99, folder="Actual Sent", in_reply_to="<1@synthetic.invalid>")],
        },
        2,
        {"folder": "Actual Sent", "limit": 20},
    )
    result = evidence(sent_context, [folders(sent_context), query])
    assert result["sent_query_observed"] is True
    assert result["rows"] == [[1, True, False, True], [2, False, False, None]]


def test_gets_no_scope_from_unknown_cohort(sent_context):
    ctx, _ = sent_context
    ctx[2].summary = "Unsupported original answer"
    result = call(sent_context)
    assert result["cohort_known"] is False and result["decisions"] == []


def test_query_limit_respects_lower_schema_maximum(sent_context):
    ctx, schemas = sent_context
    schemas["list_emails"]["properties"]["limit"]["maximum"] = 10
    rules = ctx[-1][ctx[5].id][1]
    rules.mcp_read_tools["list_emails"] = schema_digest(schemas["list_emails"])
    ctx[6].rules = rules.model_dump_json()
    decision = call(sent_context, [folders(sent_context)])["decisions"][0]
    assert decision["arguments"]["arguments"]["limit"] == 10


def test_malformed_folder_discovery_does_not_establish_observation(sent_context):
    discovery = step(sent_context, "list_folders", [{"name": "Actual Sent", "flags": ["\\Sent"]}])
    assert evidence(sent_context, [discovery])["sent_discovery_observed"] is False
