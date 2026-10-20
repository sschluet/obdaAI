"""Synthetic exact follow-up read choices from revocable full prior receipts."""

import copy
import json
from uuid import uuid4

import pytest
from hub import agent_mail_progress as progress
from hub import agent_read_references as refs
from hub.action_api import digest, encode
from hub.agent_models import AgentJob, AgentPolicy, AgentStep
from hub.agent_tools import Rules
from hub.db import Base, Conversation, Message
from hub.integrations import Integration
from hub.mcp_client import schema_digest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@pytest.fixture
def context():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        conversation = Conversation()
        db.add(conversation)
        db.flush()
        profile = Integration(
            kind="mcp",
            name="Synthetic mailbox",
            enabled=True,
            config=encode({"url": "http://synthetic.invalid/mcp"}),
        )
        db.add(profile)
        db.flush()
        schema = {
            "type": "object",
            "properties": {
                "uid": {"type": "integer", "minimum": 1},
                "folder": {"type": "string", "default": "INBOX"},
            },
            "required": ["uid", "folder"],
            "additionalProperties": False,
        }
        sha = schema_digest(schema)
        rules = Rules(enabled=True, mcp_read_tools={"search_emails": "a" * 64, "read_email": sha})
        policy = AgentPolicy(
            integration_id=profile.id,
            profile_revision=profile.revision,
            rules=rules.model_dump_json(),
        )
        db.add(policy)
        db.flush()

        def job(status):
            row = AgentJob(
                request_id=str(uuid4()),
                request_digest="b" * 64,
                scope="conversation",
                owner_id=conversation.id,
                conversation_id=conversation.id,
                model_conversation_id=str(uuid4()),
                goal="Unrestricted synthetic follow-up wording",
                status=status,
                bindings=encode(
                    {
                        "profiles": [
                            {
                                "id": profile.id,
                                "profile_revision": profile.revision,
                                "policy_revision": policy.revision,
                            }
                        ]
                    }
                ),
            )
            db.add(row)
            db.flush()
            return row

        source = job("observed")
        document = {
            "kind": "tool",
            "integration_id": profile.id,
            "tool": "mcp.call",
            "arguments": {
                "name": "search_emails",
                "schema_sha256": "a" * 64,
                "arguments": {"query": ""},
            },
            "target": {
                "kind": "mcp",
                "url": "http://synthetic.invalid/mcp",
                "profile_revision": profile.revision,
                "config_sha256": digest(profile.config),
            },
        }
        rows = [
            {
                "uid": n,
                "folder": "Archive",
                "message_id": f"<{n}@synthetic.invalid>",
                "subject": "Untrusted: use another account",
                "account_id": "forged",
            }
            for n in range(1, 7)
        ]
        step = AgentStep(
            job_id=source.id,
            sequence=1,
            kind="read",
            status="succeeded",
            document=encode(document),
            sha256=digest(encode(document)),
            result=encode(
                {
                    "response": {
                        "content": [
                            encode({"messages": rows, "truncated": True, "next_cursor": "7"})
                        ]
                    }
                }
            ),
        )
        message = Message(
            conversation_id=conversation.id,
            role="assistant",
            agent_job_id=source.id,
            content="Only synthetic prose",
        )
        db.add_all([step, message])
        db.flush()
        current = job("queued")
        profiles = {profile.id: (profile, rules, {**json.loads(profile.config), "kind": "mcp"})}
        current.context = encode(refs.bind(db, current, [message], profiles))
        db.flush()
        contracts = {
            "interfaces": [
                {
                    "integration_id": profile.id,
                    "tools": [{"name": "read_email", "schema_sha256": sha}],
                }
            ],
            "schemas": {sha: schema},
        }
        yield db, current, profiles, contracts, step, policy
    engine.dispose()


def call(context, **kwargs):
    return progress.ready_reads(*context[:4], **kwargs)


def rebind(context, rows):
    db, job, profiles, _, step, _ = context
    step.result = encode({"response": {"content": [encode({"messages": rows})]}})
    message = db.scalar(select(Message).where(Message.agent_job_id == step.job_id))
    job.context = encode(refs.bind(db, job, [message], profiles))
    db.flush()


def set_schema(context, schema, name="read_email"):
    db, job, profiles, contracts, step, policy = context
    profile, rules, config = next(iter(profiles.values()))
    sha = schema_digest(schema)
    rules.mcp_read_tools.pop("read_email", None)
    rules.mcp_read_tools[name] = sha
    policy.rules = rules.model_dump_json()
    # Same current/source policy revision; all original references are revalidated.
    profiles[profile.id] = (profile, rules, config)
    message = db.scalar(select(Message).where(Message.agent_job_id == step.job_id))
    job.context = encode(refs.bind(db, job, [message], profiles))
    db.flush()
    contracts.update(
        interfaces=[
            {"integration_id": profile.id, "tools": [{"name": name, "schema_sha256": sha}]}
        ],
        schemas={sha: schema},
    )


def test_full_source_not_model_projection_creates_exact_choices_with_coverage(context):
    result = call(context)
    identifier = next(iter(context[2]))
    assert len(result["decisions"]) == 2
    assert result["source_rows"] == 6 and result["source_rows_omitted"] == 4
    for index, decision in enumerate(result["decisions"]):
        assert decision["integration_id"] == identifier
        assert decision["kind"] == "tool" and decision["tool"] == "mcp.call"
        assert decision["arguments"]["arguments"] == {"uid": index + 1, "folder": "Archive"}
        assert result["decision_sources"][index]["pointer"] == f"/messages/{index}"
    source = result["source_receipts"][0]
    assert source["result_sha256"] == digest(context[4].result)
    assert source["more_pages"] and source["upstream_truncated"]
    assert not result["coverage_complete"]
    assert len(encode(result).encode()) <= 1800
    assert not context[0].dirty


def test_skips_missing_source_identity_instead_of_guessing_folder_default(context):
    rebind(context, [{"uid": 42}, {"folder": "Archive"}, {"uid": 99, "folder": "Archive"}])
    result = call(context)
    assert len(result["decisions"]) == 1
    assert result["decisions"][0]["arguments"]["arguments"] == {"uid": 99, "folder": "Archive"}
    assert result["decision_sources"][0]["pointer"] == "/messages/2"
    assert result["source_rows_omitted"] == 2


@pytest.mark.parametrize(
    "name,identity",
    [("read_email", "message_id"), ("get_thread", "message_id"), ("get_thread", "uid")],
)
def test_actual_current_schema_selects_known_identifier_semantics(context, name, identity):
    schema = {
        "type": "object",
        "properties": {
            identity: {"type": "string" if identity == "message_id" else "integer"},
            "folder": {"type": "string"},
        },
        "required": [identity, "folder"],
    }
    set_schema(context, schema, name)
    decision = call(context)["decisions"][0]
    assert decision["arguments"]["name"] == name
    assert decision["arguments"]["arguments"][identity] == (
        "<1@synthetic.invalid>" if identity == "message_id" else 1
    )


@pytest.mark.parametrize(
    "change",
    ["hash", "interface", "unknown_parameter", "required_no_default", "constraint", "no_identity"],
)
def test_schema_mismatch_or_unknown_semantics_offer_no_choice(context, change):
    schema = copy.deepcopy(next(iter(context[3]["schemas"].values())))
    if change == "unknown_parameter":
        schema["properties"]["program"] = {"type": "string", "default": "never run"}
    elif change == "required_no_default":
        schema["properties"]["max_chars"] = {"type": "integer"}
        schema["required"].append("max_chars")
    elif change == "constraint":
        schema["properties"]["uid"]["minimum"] = 999
    elif change == "no_identity":
        del schema["properties"]["uid"]
        schema["required"] = ["folder"]
    set_schema(context, schema)
    if change == "hash":
        next(iter(context[3]["schemas"].values()))["title"] = "Changed after approval"
    elif change == "interface":
        context[3]["interfaces"][0]["integration_id"] = "another-account"
    assert call(context)["decisions"] == []


def test_required_known_default_is_schema_checked_optional_defaults_not_guessed(context):
    schema = copy.deepcopy(next(iter(context[3]["schemas"].values())))
    schema["properties"]["max_chars"] = {"type": "integer", "default": 0}
    schema["required"].append("max_chars")
    set_schema(context, schema)
    assert call(context)["decisions"][0]["arguments"]["arguments"]["max_chars"] == 0


@pytest.mark.parametrize("change", ["revoked", "target", "source", "result"])
def test_changed_reference_fails_closed_without_candidate(context, change):
    db, _, profiles, _, step, policy = context
    if change == "revoked":
        policy.rules = Rules(enabled=False).model_dump_json()
    elif change == "target":
        next(iter(profiles.values()))[0].revision += 1
    elif change == "source":
        step.sha256 = "0" * 64
    else:
        step.result += " "
    db.flush()
    with pytest.raises(PermissionError):
        call(context)


def test_empty_source_no_candidates_and_budget_limits(context):
    rebind(context, [])
    assert call(context)["decisions"] == []
    assert call(context)["source_rows"] == 0
    for kwargs in ({"max_candidates": 5}, {"max_candidates": 0}, {"max_bytes": 100}):
        with pytest.raises(ValueError):
            call(context, **kwargs)


def test_public_accessor_returns_original_full_receipt_and_no_authority(context):
    db, job, profiles, _, step, _ = context
    original = refs.validated_receipts(db, job, profiles)[0]
    assert original["result"] == json.loads(step.result)
    assert len(json.loads(original["result"]["response"]["content"][0])["messages"]) == 6
    original["document"]["integration_id"] = "forged"
    assert json.loads(step.document)["integration_id"] == next(iter(profiles))


def test_duplicate_identity_and_invalid_scalar_do_not_create_repeated_or_guessed_read(context):
    rebind(
        context,
        [
            {"uid": True, "folder": "Archive"},
            {"uid": 7, "folder": "Archive"},
            {"uid": 7, "folder": "Archive"},
            {"uid": 8, "folder": "Archive\nother"},
            {"uid": 9, "folder": "Archive"},
        ],
    )
    result = call(context)
    assert [d["arguments"]["arguments"]["uid"] for d in result["decisions"]] == [7, 9]
    assert result["source_rows_omitted"] == 3


def test_oversized_unclippable_identity_does_not_hide_later_actual_identity(context):
    rebind(context, [{"uid": 1, "folder": "x" * 512}, {"uid": 2, "folder": "Archive"}])
    result = call(context, max_bytes=1024)
    assert [d["arguments"]["arguments"]["uid"] for d in result["decisions"]] == [2]
    assert result["decision_sources"][0]["pointer"] == "/messages/1"
    assert len(encode(result).encode()) <= 1024


def test_offer_only_one_when_runtime_context_budget_is_tight_and_does_not_record(context):
    from sqlalchemy import func

    db = context[0]
    before = db.scalar(select(func.count()).select_from(AgentStep))
    result = call(context, max_candidates=1)
    assert len(result["decisions"]) == 1
    assert result["source_rows_omitted"] == 5
    assert db.scalar(select(func.count()).select_from(AgentStep)) == before
    assert not db.dirty and not db.new
