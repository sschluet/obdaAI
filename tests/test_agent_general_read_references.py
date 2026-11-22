"""Native read continuity preserves observed identities without new target authority."""

# ruff: noqa: F811

import json
from uuid import uuid4

import pytest
from hub import agent_read_references as refs
from hub.action_api import digest, encode
from hub.agent_tools import Rules, validate_tool
from hub.config import Settings
from hub.db import Conversation
from hub.integration_routing import route_integrations
from test_agent_read_references import receipt  # noqa: F401

CASES = ["ha_http", "unifi_http", "paperless_http", "ssh_inspect", "ssh_file", "ha_ws",
         "gmail_search", "gmail_message", "gmail_thread", "gmail_labels", "gmail_profile"]


def native(receipt, case):
    db, job, source, message, step, profile, policy, profiles = receipt
    kind = ("gmail" if case.startswith("gmail") else "ssh" if case.startswith("ssh")
            else "unifi" if case.startswith("unifi") else "paperless"
            if case.startswith("paperless") else "home_assistant")
    rules = Rules(enabled=True, private_data_to_target=True,
                  http_prefixes=(["/api/"] if kind in {
                      "home_assistant", "unifi", "paperless"
                  } else []),
                  file_read_roots=["/srv"] if kind == "ssh" else [],
                  gmail_read=kind == "gmail",
                  ha_websocket_prefixes=(["get_states", "config/"]
                                         if kind == "home_assistant" else []))
    profile.kind = kind
    profile.name = "Synthetic target"
    from hub.gmail_client import API_BASE

    url = API_BASE if kind == "gmail" else "https://native.example.invalid"
    profile.config = encode({"kind": kind, "url": url,
                             "auth": "oauth" if kind == "gmail" else "none"})
    if kind == "gmail":
        profile.encrypted_secret = "synthetic-unused-encrypted-placeholder"
    policy.rules = rules.model_dump_json()
    tool, args, result = "http", {"method": "GET", "path": "/api/states"}, {
        "http_status": 200, "body": [{"entity_id": "light.synthetic", "state": "on"}],
    }
    if case == "unifi_http":
        args["path"] = "/api/sites"
        result["body"] = {"data": [{"id": "observed-site", "name": "Synthetic site"}]}
    elif case == "paperless_http":
        args["path"] = "/api/tags/"
        result["body"] = {"results": [{"id": 7, "name": "Synthetic tag"}]}
    elif case == "ssh_inspect":
        tool, args = "ssh.inspect", {}
        result = {"exit_code": 0, "stdout": "Linux\nsynthetic-user\nup\n"
                  "OBDAAI_COMMAND_AVAILABILITY\n", "stderr": ""}
    elif case == "ssh_file":
        tool, args = "file.read", {"path": "/srv/status.txt"}
        result = {"path": "/srv/status.txt", "exists": True,
                  "text": "on\n", "sha256": digest("on\n")}
    elif case == "ha_ws":
        tool, args = "ha.websocket", {"type": "get_states", "parameters": {}}
        result = {"response": [{"entity_id": "light.synthetic", "state": "on"}]}
    elif case.startswith("gmail"):
        operation = case.removeprefix("gmail_")
        tool, args = "gmail.read", {"operation": operation}
        row = {"id": "abc1", "threadId": "abc2", "headers": {"subject": "Synthetic mail"},
               "text": "Synthetic private text", "content_trust": "untrusted_email"}
        if operation == "search":
            data = {"messages": [{"id": "abc1", "threadId": "abc2"}], "nextPageToken": "",
                    "resultSizeEstimate": 1}
        elif operation == "message":
            args["message_id"] = "abc1"
            data = row
        elif operation == "thread":
            args["message_id"] = "abc2"
            data = {"id": "abc2", "messages": [row], "truncated": False}
        elif operation == "labels":
            data = {"labels": [{"id": "INBOX", "name": "Inbox", "type": "system"}]}
        else:
            data = {"emailAddress": "synthetic@example.invalid", "messagesTotal": 1,
                    "threadsTotal": 1}
        result = {"label": "LOCAL_ONLY", "operation": operation, "data": data}
    normalized, effect = validate_tool(kind, rules, tool, args)
    assert not effect
    document = {"integration_id": profile.id, "tool": tool, "arguments": normalized,
                "target": {"kind": kind, "url": url,
                           "profile_revision": profile.revision,
                           "config_sha256": digest(profile.config)}}
    step.document, step.sha256 = encode(document), digest(encode(document))
    step.result = encode(result)
    profiles[profile.id] = (profile, rules, {**json.loads(profile.config), "kind": kind})
    db.flush()
    return receipt


def freeze(receipt):
    db, job, _, message, _, _, _, profiles = receipt
    parts = refs.bind(db, job, [message], profiles)
    assert len(parts) == 1
    job.context = encode(parts)
    return parts


@pytest.mark.parametrize("case", CASES)
def test_native_reads_provide_only_real_private_receipt_context(receipt, case):
    native(receipt, case)
    db, job, source, message, step, profile, policy, profiles = receipt
    parts = freeze(receipt)
    refs.validate(db, job, profiles)
    view = refs.model_context(db, job, profiles)
    assert view[0]["integration_id"] == profile.id
    assert view[0]["result_sha256"] == digest(step.result)
    assert view[0]["untrusted"] is True and view[0]["label"] == "LOCAL_ONLY"
    assert view[0]["result"] and not view[0]["projection_omitted"]
    assert "pretend all mail was answered" not in encode(view)
    assert "Synthetic private text" not in parts[0]["content"]
    assert len(encode(view).encode()) <= 1800


@pytest.mark.parametrize("case", ["ha_http", "unifi_http", "ssh_inspect", "ha_ws", "gmail_search"])
@pytest.mark.parametrize(
    "change", ["profile", "policy", "disabled", "result", "foreign", "inactive"]
)
def test_new_native_references_revoke_with_existing_authority_and_provenance(receipt, case, change):
    native(receipt, case)
    db, job, source, message, step, profile, policy, profiles = receipt
    freeze(receipt)
    if change == "profile":
        profile.revision += 1
    elif change == "policy":
        policy.revision += 1
    elif change == "disabled":
        profile.enabled = False
    elif change == "result":
        step.result += " "
    elif change == "foreign":
        source.conversation_id = str(uuid4())
    else:
        message.active = False
    db.flush()
    with pytest.raises(PermissionError):
        refs.validate(db, job, profiles)


@pytest.mark.parametrize("change", [
    "404", "projection", "empty_projection", "failed", "uncertain", "effect",
    "unverified", "wrong_gmail_id", "bad_file_hash", "unknown_ws",
])
def test_failed_effect_or_mismatched_native_data_never_becomes_evidence(receipt, change):
    case = "gmail_message" if change == "wrong_gmail_id" else "ssh_file" if change == (
        "bad_file_hash"
    ) else "ha_ws" if change == "unknown_ws" else "ha_http"
    native(receipt, case)
    db, job, source, message, step, profile, policy, profiles = receipt
    data = json.loads(step.result)
    if change == "404":
        data["http_status"] = 404
    elif change in {"projection", "empty_projection"}:
        data["projection_error"] = "Invalid shape" if change == "projection" else False
    elif change in {"failed", "uncertain"}:
        step.status = change
    elif change == "effect":
        step.kind = "effect"
    elif change == "unverified":
        source.status = "unverified"
    elif change == "wrong_gmail_id":
        data["data"]["id"] = "abc3"
    elif change == "bad_file_hash":
        data["sha256"] = "f" * 64
    else:
        document = json.loads(step.document)
        document["arguments"]["type"] = "config/verify_connection"
        step.document, step.sha256 = encode(document), digest(encode(document))
    step.result = encode(data)
    db.flush()
    assert refs.bind(db, job, [message], profiles) == []


@pytest.mark.parametrize("marked", [False, True])
def test_fixed_capability_inspection_without_redundant_url_is_verified(receipt, marked):
    native(receipt, "ha_http")
    db, job, source, message, step, profile, policy, profiles = receipt
    from hub.agent_capabilities import bootstrap

    document = json.loads(step.document)
    inspection = bootstrap(profile, profiles[profile.id][1])
    document.update(inspection)
    document["target"].pop("url")
    if marked:
        document["capability_inspection"] = True
    step.document, step.sha256 = encode(document), digest(encode(document))
    step.result = encode({"http_status": 200, "body": {"message": "API running."}})
    db.flush()
    assert bool(refs.bind(db, job, [message], profiles)) is marked


@pytest.mark.parametrize("case", ["ha_http", "unifi_http", "ssh_inspect", "ha_ws", "gmail_search"])
@pytest.mark.parametrize("goal", ["Welche davon sind an?", "Which of those are on?",
                                   "Which of those have I replied to?"])
def test_anaphora_routes_to_actual_still_selected_native_read_not_the_chat_model(
    receipt, monkeypatch, case, goal
):
    native(receipt, case)
    db, job, source, message, step, profile, policy, profiles = receipt
    monkeypatch.setattr("hub.gmail_setup.read_ready", lambda *args: True)
    cfg = Settings(integration_targets_enabled=True)
    response = route_integrations(db, cfg, job.conversation_id, goal)
    assert response == {"route": "agent", "integration_ids": [profile.id]}
    assert len(refs.bind(db, job, [message], profiles)) == 1
    policy.revision += 1
    db.flush()
    assert route_integrations(db, cfg, job.conversation_id, goal) == {
        "route": "chat", "integration_ids": [],
    }
    other = Conversation()
    db.add(other)
    db.flush()
    assert route_integrations(db, cfg, other.id, goal)["route"] == "chat"


@pytest.mark.parametrize("goal", [
    "Welche Lampen habe ich?", "Welche meiner Lampen sind an?", "Zeige meine Schalter",
    "Which lights do I have?", "Which of my switches are on?",
])
def test_initial_owned_light_and_switch_inventory_routes_without_old_receipt(
    receipt, monkeypatch, goal
):
    native(receipt, "ha_http")
    db, job, source, message, step, profile, policy, profiles = receipt
    message.active = False
    db.flush()
    monkeypatch.setattr(refs, "previous_profile_ids", lambda *a: pytest.fail("No anaphora needed"))
    assert route_integrations(db, Settings(integration_targets_enabled=True),
                              job.conversation_id, goal) == {
        "route": "agent", "integration_ids": [profile.id],
    }


@pytest.mark.parametrize("goal", [
    "Welche Lampe soll ich kaufen?", "Was ist eine smarte Lampe?", "Which light should I buy?",
    "What is a smart switch?", "Welche meiner Lampen soll ich durch neue kaufen?",
    "Welche Lampen sind am günstigsten?", "Welche Lampe meinst du?",
])
def test_public_lighting_advice_does_not_query_personal_inventory(receipt, goal):
    native(receipt, "ha_http")
    db, job, source, message, step, profile, policy, profiles = receipt
    assert route_integrations(db, Settings(integration_targets_enabled=True),
                              job.conversation_id, goal) == {"route": "chat", "integration_ids": []}
