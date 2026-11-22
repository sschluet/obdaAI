"""Followups retain the latest displayed authenticated cohort across topic changes."""

import json
import time
from uuid import uuid4

from hub import agent_read_references as refs
from hub.action_api import digest, encode
from hub.agent_models import AgentJob, AgentPolicy, AgentStep
from hub.agent_tools import Rules
from hub.db import Message
from hub.integrations import Integration
from test_agent_read_references import receipt  # noqa: F401


def test_latest_displayed_account_does_not_merge_an_older_other_account(receipt):  # noqa: F811
    db, job, source, message, step, profile, policy, profiles = receipt
    second = Integration(kind="mcp", name="Second synthetic mailbox", enabled=True,
                         config=encode({"url": "http://second.invalid/mcp"}))
    db.add(second)
    db.flush()
    second_policy = AgentPolicy(integration_id=second.id, profile_revision=second.revision,
                                rules=policy.rules)
    db.add(second_policy)
    db.flush()
    binding = {"id": second.id, "profile_revision": second.revision,
               "policy_revision": second_policy.revision}
    newer = AgentJob(
        request_id=str(uuid4()), request_digest="c" * 64, scope="conversation",
        owner_id=job.owner_id, conversation_id=job.conversation_id,
        model_conversation_id=str(uuid4()), goal="Second account overview", status="observed",
        bindings=encode({"profiles": [binding]}),
    )
    db.add(newer)
    db.flush()
    document = json.loads(step.document)
    document["integration_id"] = second.id
    document["target"].update(url="http://second.invalid/mcp",
                               profile_revision=second.revision,
                               config_sha256=digest(second.config))
    newer_step = AgentStep(job_id=newer.id, sequence=1, kind="read", status="succeeded",
                           document=encode(document), sha256=digest(encode(document)),
                           result=step.result)
    newer_message = Message(conversation_id=job.conversation_id, role="assistant",
                            agent_job_id=newer.id, content="Second synthetic overview")
    db.add_all([newer_step, newer_message])
    db.flush()
    profiles[second.id] = (second, profiles[profile.id][1],
                           {"kind": "mcp", "url": "http://second.invalid/mcp"})
    bindings = json.loads(job.bindings)
    bindings["profiles"].append(binding)
    job.bindings = encode(bindings)
    job.created = time.time()  # Destination is created after both actual source receipts.
    db.flush()
    parts = refs.bind(db, job, [message, newer_message], profiles)
    assert len(parts) == 1 and json.loads(parts[0]["content"])["integration_id"] == second.id
    assert refs.previous_profile_ids(db, job.conversation_id, profiles) == {second.id}
    job.context = encode(parts)
    refs.validate(db, job, profiles)
    second_policy.rules = Rules(enabled=False).model_dump_json()
    db.flush()
    assert refs.bind(db, job, [message, newer_message], profiles) == []
    assert refs.previous_profile_ids(db, job.conversation_id, profiles) == set()
    profiles.pop(second.id)
    assert refs.bind(db, job, [message, newer_message], profiles) == []


def test_intervening_ordinary_assistant_topic_blocks_older_cohort_but_user_turns_do_not(receipt):  # noqa: F811
    db, job, _, message, _, _, _, profiles = receipt
    ordinary = Message(conversation_id=job.conversation_id, role="assistant",
                       content="An unrelated ordinary topic", created=message.created + 1)
    user = Message(conversation_id=job.conversation_id, role="user",
                   content="Which of those?", created=message.created + 2)
    db.add_all([ordinary, user])
    db.flush()
    job.created = user.created + 1
    assert refs.bind(db, job, [message, ordinary, user], profiles) == []
    ordinary.active = False
    assert len(refs.bind(db, job, [message, ordinary, user], profiles)) == 1
    db.flush()


def test_invalid_latest_receipt_never_reactivates_older_valid_account(receipt):  # noqa: F811
    db, job, source, message, step, profile, policy, profiles = receipt
    old = Message(conversation_id=job.conversation_id, role="assistant", agent_job_id=source.id,
                  content="Older valid source", created=message.created - 1)
    latest_source = AgentJob(
        request_id=str(uuid4()), request_digest="d" * 64, scope="conversation",
        owner_id=job.owner_id, conversation_id=job.conversation_id,
        model_conversation_id=str(uuid4()), goal="Latest source", status="observed",
        bindings=source.bindings,
    )
    db.add_all([old, latest_source])
    db.flush()
    latest_step = AgentStep(job_id=latest_source.id, sequence=1, kind="read", status="failed",
                           document=step.document, sha256=step.sha256, result=step.result)
    latest = Message(conversation_id=job.conversation_id, role="assistant",
                     agent_job_id=latest_source.id, content="Latest unavailable source")
    db.add_all([latest_step, latest])
    db.flush()
    job.created = time.time()
    assert refs.bind(db, job, [old, latest], profiles) == []
    # Source policy revocation is equally terminal; a newer failed/invalid source
    # may never be skipped merely to find an older successful source.
    latest_step.status = "succeeded"
    latest_source.status = "unverified"
    assert refs.bind(db, job, [old, latest], profiles) == []
