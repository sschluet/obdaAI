"""Explicit preview and durable single-attempt mail delivery API regressions."""

import json
import time
from uuid import uuid4

import pytest
from hub.db import Run
from hub.integrations import Integration
from hub.use_case_delivery import MailDelivery, MailPreview
from hub.use_cases import UseCaseRun
from sqlalchemy import func, select
from test_use_case_ai import ai_spec

pytest_plugins = ["test_knowledge"]


def smtp(app, name="Synthetic mail"):
    with app.state.sessions() as db:
        row = Integration(
            name=name,
            kind="smtp",
            enabled=True,
            config=json.dumps(
                {
                    "url": "mail.example.test",
                    "port": 465,
                    "username": "synthetic",
                    "sender": "sender@example.test",
                }
            ),
            encrypted_secret="synthetic-encrypted",
            last_check=json.dumps({"revision": 1, "status": "succeeded"}),
        )
        db.add(row)
        db.commit()
        return row.id


@pytest.fixture
def delivery(knowledge, monkeypatch):
    app, client, headers, _, _ = knowledge
    identifier = smtp(app)
    spec = ai_spec()
    case = client.post("/api/use-cases", headers=headers, json={"spec": spec}).json()
    with app.state.sessions() as db:
        row = UseCaseRun(
            use_case_id=case["id"],
            revision=1,
            request_id=str(uuid4()),
            request_digest="0" * 64,
            created=time.time(),
            snapshot=json.dumps({"spec": spec, "output": {"text": "Synthetic result"}}),
        )
        db.add(row)
        db.commit()
        run_id = row.id
    monkeypatch.setattr("hub.use_case_delivery.decrypt", lambda *args: "synthetic-password")
    calls = []

    class Connection:
        def close(self):
            calls.append("close")

    def connect(*args):
        calls.append("connect")
        return Connection()

    def send(connection, message, boundary):
        calls.append("send")
        assert message["To"] == "recipient@example.test"
        boundary()
        calls.append("data")

    monkeypatch.setattr("hub.use_case_delivery.connect", connect)
    monkeypatch.setattr("hub.use_case_delivery.send", send)
    return app, client, headers, case, run_id, identifier, calls


def path(d):
    return f"/api/use-cases/{d[3]['id']}/runs/{d[4]}"


def preview(d, **changes):
    body = {
        "integration_id": d[5],
        "expected_revision": 1,
        "recipient": "recipient@example.test",
        "subject": "Synthetic result",
        **changes,
    }
    return d[1].post(path(d) + "/delivery-preview", headers=d[2], json=body)


def send(d, value, **changes):
    return d[1].post(
        path(d) + "/deliveries",
        headers=d[2],
        json={
            "preview_id": value["preview_id"],
            "digest": value["digest"],
            "request_id": str(uuid4()),
            **changes,
        },
    )


def test_explicit_preview_has_no_network_single_attempt_replay(delivery):
    d = delivery
    value = preview(d).json()
    assert value["text"] == "Synthetic result" and d[6] == []
    key = str(uuid4())
    first = send(d, value, request_id=key)
    assert first.status_code == 200 and first.json()["status"] == "sent"
    again = send(d, value, request_id=key)
    assert again.json() == first.json()
    assert d[6].count("data") == 1
    assert send(d, value).status_code == 409


@pytest.mark.parametrize("mutation", ["disabled", "revision", "expired", "result", "case"])
def test_changed_preview_blocks_before_network(delivery, mutation):
    d = delivery
    value = preview(d).json()
    with d[0].state.sessions() as db:
        if mutation in {"disabled", "revision"}:
            row = db.get(Integration, d[5])
            if mutation == "disabled":
                row.enabled = False
            else:
                row.revision += 1
        elif mutation == "expired":
            db.get(MailPreview, value["preview_id"]).expires = 0
        elif mutation == "result":
            row = db.get(UseCaseRun, d[4])
            changed = json.loads(row.snapshot)
            changed["output"]["text"] = "Changed result"
            row.snapshot = json.dumps(changed)
        else:
            from hub.use_cases import UseCase

            db.get(UseCase, d[3]["id"]).revision += 1
        db.commit()
    assert send(d, value).status_code == 409
    assert d[6] == []


def test_wrong_digest_or_nonfinished_result_rejected(delivery):
    d = delivery
    value = preview(d).json()
    assert send(d, value, digest="f" * 64).status_code == 409
    with d[0].state.sessions() as db:
        from hub.db import Conversation

        conversation = Conversation(purpose="use_case", title="Synthetic")
        db.add(conversation)
        db.flush()
        run = Run(conversation_id=conversation.id, status="failed")
        db.add(run)
        db.flush()
        db.get(UseCaseRun, d[4]).execution_run_id = run.id
        db.commit()
    assert preview(d).status_code == 409
    assert d[6] == []


@pytest.mark.parametrize("after_boundary", [False, True])
def test_failure_receipt_distinguishes_handoff_without_retry(delivery, monkeypatch, after_boundary):
    d = delivery

    def fail(connection, message, boundary):
        if after_boundary:
            boundary()
        raise OSError("Synthetic disconnect")

    monkeypatch.setattr("hub.use_case_delivery.send", fail)
    value = preview(d).json()
    key = str(uuid4())
    result = send(d, value, request_id=key)
    assert result.json()["status"] == ("uncertain" if after_boundary else "failed")
    assert send(d, value, request_id=key).json() == result.json()
    assert send(d, value).status_code == 409
    assert d[6].count("connect") == 1


def test_primary_cas_selection_priority_and_revision_block(delivery):
    d = delivery
    default = d[1].put(
        "/api/integrations/mail-default",
        headers=d[2],
        json={"integration_id": d[5], "expected_revision": 0},
    )
    assert default.status_code == 200 and default.json()["revision"] == 1
    assert (
        d[1]
        .put(
            "/api/integrations/mail-default",
            headers=d[2],
            json={"integration_id": d[5], "expected_revision": 0},
        )
        .status_code
        == 409
    )
    chosen_default = preview(d, integration_id=None).json()
    assert chosen_default["default_revision"] == 1
    other = smtp(d[0], "Explicit mail")
    with d[0].state.sessions() as db:
        row = db.get(UseCaseRun, d[4])
        snapshot = json.loads(row.snapshot)
        snapshot["spec"]["output_integration_id"] = other
        row.snapshot = json.dumps(snapshot)
        db.commit()
    configured = preview(d, integration_id=None).json()
    assert configured["integration_id"] == other and configured["default_revision"] is None
    explicit = preview(d).json()
    assert explicit["integration_id"] == d[5]
    d[1].put(
        "/api/integrations/mail-default",
        headers=d[2],
        json={"integration_id": other, "expected_revision": 1},
    )
    assert send(d, chosen_default).status_code == 409
    assert d[6] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("recipient", "a@example.test\r\nBcc: other@example.test"),
        ("recipient", "a@example.test,b@example.test"),
        ("subject", "Result\nBcc: other@example.test"),
    ],
)
def test_header_injection_preview_blocked(delivery, field, value):
    assert preview(delivery, **{field: value}).status_code == 422
    assert delivery[6] == []


def test_deletion_cleans_own_previews_and_blocks_active_delivery(delivery):
    d = delivery
    value = preview(d).json()
    with d[0].state.sessions() as db:
        pending = MailDelivery(
            preview_id=value["preview_id"],
            request_id=str(uuid4()),
            status="sending",
            message_id="<synthetic@example.test>",
            created=time.time(),
        )
        db.add(pending)
        db.commit()
        pending_id = pending.id
    url = f"/api/use-cases/{d[3]['id']}"
    assert (
        d[1].request("DELETE", url, headers=d[2], json={"expected_revision": 1}).status_code == 409
    )
    with d[0].state.sessions() as db:
        db.get(MailDelivery, pending_id).status = "sent"
        db.commit()
    removed = d[1].request("DELETE", url, headers=d[2], json={"expected_revision": 1})
    assert removed.status_code == 200, removed.text
    with d[0].state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(MailDelivery)) == 0
        assert db.scalar(select(func.count()).select_from(MailPreview)) == 0


def test_deactivation_after_connect_is_rechecked_before_data(delivery, monkeypatch):
    d = delivery

    def connect(*args):
        with d[0].state.sessions() as db:
            db.get(Integration, d[5]).enabled = False
            db.commit()

        class Connection:
            def close(self):
                pass

        return Connection()

    monkeypatch.setattr("hub.use_case_delivery.connect", connect)
    value = preview(d).json()
    response = send(d, value)
    assert response.json()["status"] == "failed"
    assert "send" in d[6] and "data" not in d[6]


def test_used_request_key_cannot_cross_preview_or_result(delivery):
    d = delivery
    first, second = preview(d).json(), preview(d).json()
    key = str(uuid4())
    assert send(d, first, request_id=key).json()["status"] == "sent"
    assert send(d, second, request_id=key).status_code == 409
    wrong_case = d[1].post(
        f"/api/use-cases/{uuid4()}/runs/{d[4]}/deliveries",
        headers=d[2],
        json={"preview_id": first["preview_id"], "digest": first["digest"], "request_id": key},
    )
    assert wrong_case.status_code == 409
    assert d[6].count("data") == 1


def test_stale_sending_receipt_becomes_uncertain_and_never_retries(delivery):
    d = delivery
    value = preview(d).json()
    key = str(uuid4())
    with d[0].state.sessions() as db:
        row = MailDelivery(
            preview_id=value["preview_id"],
            request_id=key,
            status="sending",
            message_id="<synthetic@example.test>",
            created=time.time() - 301,
        )
        db.add(row)
        db.commit()
    records = d[1].get(path(d) + "/deliveries", headers=d[2])
    assert records.json()[0]["status"] == "uncertain"
    assert send(d, value, request_id=key).json()["status"] == "uncertain"
    assert d[6] == []


def test_stalled_replay_transition_is_durable(delivery):
    d = delivery
    value = preview(d).json()
    key = str(uuid4())
    with d[0].state.sessions() as db:
        row = MailDelivery(
            preview_id=value["preview_id"],
            request_id=key,
            status="sending",
            message_id="<synthetic@example.test>",
            created=time.time() - 301,
        )
        db.add(row)
        db.commit()
        identifier = row.id
    assert send(d, value, request_id=key).json()["status"] == "uncertain"
    with d[0].state.sessions() as db:
        assert db.get(MailDelivery, identifier).status == "uncertain"
    assert d[6] == []


@pytest.mark.parametrize("kind", ["named", "explicit", "unknown", "disabled", "ambiguous"])
def test_mail_choice_defined_prompt_without_automatic_network(delivery, kind):
    d = delivery
    other = smtp(d[0], "Firmenpost")
    d[1].put(
        "/api/integrations/mail-default",
        headers=d[2],
        json={"integration_id": d[5], "expected_revision": 0},
    )
    with d[0].state.sessions() as db:
        row = db.get(UseCaseRun, d[4])
        snapshot = json.loads(row.snapshot)
        snapshot["spec"]["processing_prompt"] = "Auswertung und Mailversand über Firmenpost"
        if kind == "explicit":
            snapshot["spec"]["output_integration_id"] = d[5]
        elif kind == "unknown":
            snapshot["spec"]["processing_prompt"] = "Mailversand über unbekannte Verbindung"
        elif kind == "disabled":
            db.get(Integration, other).enabled = False
        elif kind == "ambiguous":
            snapshot["spec"]["processing_prompt"] += "\nE-Mail via Synthetic mail"
        row.snapshot = json.dumps(snapshot)
        db.commit()
    response = preview(d, integration_id=None)
    if kind in {"disabled", "ambiguous"}:
        assert response.status_code == 409
    else:
        assert response.status_code == 200, response.text
        assert response.json()["integration_id"] == (other if kind == "named" else d[5])
    assert d[6] == []


def test_explicit_preview_choice_overrides_ambiguous_prompt(delivery):
    d = delivery
    smtp(d[0], "Firmenpost")
    with d[0].state.sessions() as db:
        row = db.get(UseCaseRun, d[4])
        snapshot = json.loads(row.snapshot)
        snapshot["spec"]["processing_prompt"] = (
            "Mailversand über Firmenpost\nE-Mail via Synthetic mail"
        )
        row.snapshot = json.dumps(snapshot)
        db.commit()
    assert preview(d, integration_id=None).status_code == 409
    response = preview(d)
    assert response.status_code == 200, response.text
    assert response.json()["integration_id"] == d[5]
    assert send(d, response.json()).json()["status"] == "sent"
    assert d[6].count("data") == 1


def test_revoked_login_at_transport_prevents_smtp_data(delivery, monkeypatch):
    from hub.db import LoginSession
    from hub.smtp_client import send as smtp_send
    from sqlalchemy import delete

    d = delivery
    value = preview(d).json()
    transport = []

    class Connection:
        def mail(self, sender):
            transport.append("mail")
            return 250, b"ok"

        def rcpt(self, recipient):
            transport.append("rcpt")
            return 250, b"ok"

        def data(self, message):
            transport.append("data")
            return 250, b"accepted"

        def close(self):
            transport.append("close")

    def connect(*args):
        with d[0].state.sessions() as db:
            db.execute(delete(LoginSession))
            db.commit()
        return Connection()

    monkeypatch.setattr("hub.use_case_delivery.connect", connect)
    monkeypatch.setattr("hub.use_case_delivery.send", smtp_send)
    response = send(d, value)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert transport == ["mail", "rcpt", "close"]
    assert d[6] == []
