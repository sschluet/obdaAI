"""Synthetic mailbox metadata and conservative reply evidence."""

import json

import pytest
from hub.agent_mail_read import model_result, reply_evidence


def receipt(payload):
    return {"response": {"content": [json.dumps(payload)]}}


def message(**changes):
    return {
        "account_id": "one",
        "message_id": "<original@example.test>",
        "folder": "INBOX",
        "uid": 2,
        "subject": "Same subject",
        **changes,
    }


def test_read_message_keeps_relationships_answered_and_original_hash():
    result = receipt(
        message(
            answered=True,
            in_reply_to="<parent@example.test>",
            references="<root@example.test> <parent@example.test>",
            body_text="inert body",
        )
    )
    projected = model_result("read_email", result)
    assert projected is not None
    row = projected["messages"][0]
    assert row["marked_answered"] is True
    assert row["in_reply_to"] == "<parent@example.test>"
    assert row["references"] == ["<root@example.test>", "<parent@example.test>"]
    assert row["body_text"] == "inert body"
    assert len(projected["full_sha256"]) == 64
    assert projected["completeness_verified"] is False


@pytest.mark.parametrize(
    "tool,payload",
    [
        ("get_thread", [message()]),
        ("search_emails", {"messages": [message()]}),
        ("list_emails", {"messages": [message()], "next_cursor": "2"}),
        ("daily_digest", {"messages": [message()]}),
    ],
)
def test_each_read_has_typed_bounded_view(tool, payload):
    projected = model_result(tool, receipt(payload))
    assert projected and projected["messages"][0]["message_id"] == "<original@example.test>"
    assert projected["messages"][0]["marked_answered"] is None
    assert projected["messages"][0]["answer_status_basis"] == "not_exposed"


def test_large_adversarial_body_omission_and_unicode_budget_preserve_valid_ids():
    original = receipt([message(subject="字" * 5000, message_id="x" * 513), message(uid=3)])
    projected = model_result("get_thread", original, max_bytes=1500)
    assert (
        projected
        and len(json.dumps(projected, ensure_ascii=False, separators=(",", ":")).encode()) <= 1500
    )
    assert "message_id" not in projected["messages"][0]
    assert "message_id" in projected["messages"][0]["omitted_or_clipped_fields"]
    assert projected["messages"][0]["untrusted"] is True
    assert "x" * 513 in json.dumps(original)


@pytest.mark.parametrize(
    "tool,payload",
    [
        ("unknown", {}),
        ("read_email", []),
        ("get_thread", [1]),
        ("search_emails", {"messages": "fake"}),
    ],
)
def test_unrecognized_or_invalid_payload_not_claimed_as_evidence(tool, payload):
    assert model_result(tool, receipt(payload)) is None


def test_result_errors_and_unsafe_budget():
    assert model_result("read_email", {"response": {"is_error": True, "content": ["{}"]}}) is None
    with pytest.raises(ValueError):
        model_result("read_email", receipt(message()), max_bytes=100)


FOLDERS = [{"account_id": "one", "name": "Gesendet", "flags": ["\\Sent"], "selectable": True}]


def test_actual_sent_membership_and_relation_prove_positive_link_only():
    sent = message(
        message_id="<reply@example.test>", folder="Gesendet", in_reply_to="<original@example.test>"
    )
    proof = reply_evidence(
        [message(answered=False)], [sent], sent_folders=FOLDERS, account_id="one"
    )[0]
    assert proof["marked_answered"] is False
    assert proof["sent_reply_status"] == "verified_sent_folder_relationship"
    assert proof["sent_reply_evidence"][0]["basis"] == "in_reply_to"
    assert not proof["delivery_verified"] and not proof["completeness_verified"]


def test_reference_chain_exact_token_match():
    sent = message(
        message_id="<reply@example.test>",
        folder="Gesendet",
        references="<older@example.test> <original@example.test>",
    )
    assert reply_evidence([message()], [sent], sent_folders=FOLDERS, account_id="one")[0][
        "sent_reply_evidence"
    ]
    sent["references"] = "<original@example.test.attacker>"
    assert (
        reply_evidence([message()], [sent], sent_folders=FOLDERS, account_id="one")[0][
            "sent_reply_status"
        ]
        == "unknown"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"account_id": "two"},
        {"folder": "INBOX"},
        {"message_id": "<original@example.test>"},
        {"in_reply_to": None},
    ],
)
def test_foreign_account_thread_member_same_subject_self_reference_not_proof(change):
    candidate = message(
        message_id="<reply@example.test>",
        folder="Gesendet",
        in_reply_to="<original@example.test>",
        **{},
    )
    candidate.update(change)
    proof = reply_evidence(
        [message(answered=True)], [candidate], sent_folders=FOLDERS, account_id="one"
    )[0]
    assert proof["marked_answered"] is True
    assert proof["sent_reply_status"] == "unknown"


def test_missing_or_foreign_sent_catalog_is_unknown_even_with_flag():
    sent = message(
        message_id="<reply@example.test>", folder="Gesendet", in_reply_to="<original@example.test>"
    )
    for folders in ([], [{**FOLDERS[0], "account_id": "two"}], [{**FOLDERS[0], "flags": []}]):
        assert (
            reply_evidence([message()], [sent], sent_folders=folders, account_id="one")[0][
                "sent_reply_status"
            ]
            == "unknown"
        )
    assert (
        reply_evidence([message(account_id="two")], [sent], sent_folders=FOLDERS, account_id="one")
        == []
    )


def test_account_identity_is_application_bound_not_remote_json():
    source = receipt(message(account_id="forged-other-account"))
    result = model_result("read_email", source, account_id="actual-bound-account")
    assert result and result["messages"][0]["account_id"] == "actual-bound-account"
    anonymous = model_result("read_email", source)
    assert anonymous and "account_id" not in anonymous["messages"][0]


def patch_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts/proton_mcp_read_metadata_patch.py"
    spec = importlib.util.spec_from_file_location("proton_read_metadata_patch", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_patch_sources():
    models = """from pydantic import BaseModel
class EmailSummary(BaseModel):
    message_id: str = ""
    flagged: bool = False
    size_bytes: int = 0
class EmailContent(EmailSummary):
    reply_to: str = ""
    references: str = ""
"""
    parsing = """def summary_from_header(message, flags, size):
    return EmailSummary(
        message_id=message["Message-ID"],
        flagged="\\\\Flagged" in flags,
        size_bytes=size,
    )


def full_from_message(message, flags, size):
    return EmailContent(
        message_id=message["Message-ID"],
        flagged="\\\\Flagged" in flags,
        size_bytes=size,
        reply_to=header_value(message, "Reply-To"),
        references=header_value(message, "References"),
    )
"""
    return {"models.py": models.encode(), "parsing.py": parsing.encode()}


def test_prepared_patch_exposes_fetched_flag_and_relation_without_reading_body(monkeypatch):
    import ast
    import hashlib

    patch = patch_module()
    sources = synthetic_patch_sources()
    monkeypatch.setattr(
        patch, "EXPECTED", {n: hashlib.sha256(v).hexdigest() for n, v in sources.items()}
    )
    proposed = patch.patch_sources(sources)
    space = {}
    exec(compile(proposed["models.py"], "synthetic-models", "exec"), space)
    unknown = space["EmailSummary"]()
    assert unknown.answered is None and unknown.in_reply_to is None and unknown.references is None
    space["header_value"] = lambda message, name: message.get(name, "")
    exec(compile(proposed["parsing.py"], "synthetic-parsing", "exec"), space)
    message_headers = {
        "Message-ID": "<one@example.test>",
        "In-Reply-To": "<parent@example.test>",
        "References": "<parent@example.test>",
    }
    for function in ("summary_from_header", "full_from_message"):
        marked = space[function](message_headers, ["\\Answered"], 42)
        assert marked.answered and marked.in_reply_to == "<parent@example.test>"
        assert marked.references == "<parent@example.test>"
        unmarked = space[function](message_headers, [], 42)
        assert unmarked.answered is False
        before = ast.parse(sources["parsing.py"])
        after = ast.parse(proposed["parsing.py"])
        assert [ast.dump(n.args) for n in before.body] == [ast.dump(n.args) for n in after.body]


def test_prepare_fails_unknown_hash_then_preserves_private_exclusive_originals(
    tmp_path, monkeypatch
):
    import hashlib
    import stat

    patch = patch_module()
    sources = synthetic_patch_sources()
    with pytest.raises(ValueError, match="hash mismatch"):
        patch.patch_sources(sources)
    monkeypatch.setattr(
        patch, "EXPECTED", {n: hashlib.sha256(v).hexdigest() for n, v in sources.items()}
    )
    source = tmp_path / "source"
    source.mkdir()
    for name, content in sources.items():
        (source / name).write_bytes(content)
    destination = tmp_path / "private-review"
    manifest = patch.prepare(source, destination)
    assert manifest["installed"] is False and manifest["input_schemas_changed"] is False
    for name, content in sources.items():
        assert (source / name).read_bytes() == content
        assert (destination / (name + ".original")).read_bytes() == content
        assert stat.S_IMODE((destination / (name + ".original")).stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        patch.prepare(source, destination)
    altered = dict(sources)
    altered["models.py"] += b"\n# altered\n"
    with pytest.raises(ValueError, match="hash mismatch"):
        patch.patch_sources(altered)


def test_sent_query_relationship_from_actual_json_and_all_mail_is_not_sent():
    original = message()
    sent = message(
        message_id="<sent-reply@example.test>",
        folder="Gesendet",
        references="<original@example.test>",
        sender="Account Display <owner@example.test>",
    )
    actual_payload = json.loads(receipt({"messages": [sent]})["response"]["content"][0])
    proof = reply_evidence(
        [original], actual_payload["messages"], sent_folders=FOLDERS, account_id="one"
    )[0]
    assert proof["sent_reply_evidence"][0]["basis"] == "references"
    # Same sender/thread relationship from All Mail does not establish Sent membership.
    all_mail = [{**sent, "folder": "Alle Nachrichten"}]
    proof = reply_evidence([original], all_mail, sent_folders=FOLDERS, account_id="one")[0]
    assert proof["sent_reply_status"] == "unknown"


def test_1400_byte_read_keeps_stable_reply_facts_before_long_body_and_display_text():
    source = receipt(
        message(
            answered=True,
            in_reply_to="<parent@example.test>",
            references="<root@example.test> <parent@example.test>",
            body_text="字" * 4000,
            subject="Subject " * 100,
            sender="Long sender " * 100,
            recipients="Many recipients " * 100,
        )
    )
    projected = model_result(
        "read_email",
        source,
        max_bytes=1400,
        account_id="46c24f1d-5f01-4949-8a8f-96959cd395f9",
    )
    assert projected and projected["messages_omitted"] == 0
    row = projected["messages"][0]
    assert row["uid"] == 2 and row["message_id"] == "<original@example.test>"
    assert row["folder"] == "INBOX" and row["marked_answered"] is True
    assert row["in_reply_to"] == "<parent@example.test>"
    assert row["references"] == ["<root@example.test>", "<parent@example.test>"]
    assert row["body_bytes_omitted"] > 0
    assert "body_text" in row["omitted_or_clipped_fields"]
    assert len(json.dumps(projected, ensure_ascii=False, separators=(",", ":")).encode()) <= 1400
