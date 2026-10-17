"""Disposable PostgreSQL: two dispatchers produce one remote effect."""

import base64
import concurrent.futures
import json
import os
import time
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from hub import integration_write_adapters as adapters
from hub.action_api import digest, encode
from hub.config import Settings
from hub.db import ActionGrant, ActionIntent, ActionPolicy, ActionReceipt, session_factory
from hub.integration_writes import execute_write
from hub.integrations import Integration, IntegrationWriteAudit
from hub.provider_settings import encrypt


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG required")
def test_concurrent_external_dispatch_is_not_replayed(tmp_path, monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only disposable loopback hub_ci allowed")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    key = tmp_path / "key"
    key.write_text(base64.b64encode(b"p" * 32).decode())
    key.chmod(0o600)
    cfg = Settings(database_url=url, secrets_key_file=str(key), integration_targets_enabled=True)
    factory = session_factory(url)
    effects = []
    state = {"id": 1, "title": "Before", "modified": "v1"}
    monkeypatch.setattr(adapters, "snapshot", lambda *a: dict(state))

    def apply(*args):
        effects.append(args[5])
        time.sleep(0.1)
        state.update(title="After", modified="v2")

    monkeypatch.setattr(adapters, "apply", apply)
    with factory() as db:
        policy = db.get(ActionPolicy, 1)
        prior = policy.paused, policy.revision
        policy.paused = False
        policy.revision += 1
        profile = Integration(
            name="Synthetic concurrent write",
            kind="paperless",
            enabled=True,
            writes_enabled=True,
            config=encode(
                {"kind": "paperless", "url": "https://synthetic.example.test", "auth": "api_key"}
            ),
        )
        db.add(profile)
        db.flush()
        profile.encrypted_secret = encrypt(cfg, "integration:" + profile.id, "synthetic-key")
        params = encode(
            {
                "integration_id": profile.id,
                "expected_revision": 1,
                "operation": "document.update_metadata",
                "arguments": {"document_id": 1, "title": "After"},
                "expected_state_sha256": digest(encode(state)),
            }
        )
        action = ActionIntent(
            request_key=str(uuid4()),
            tool_id="integration.write",
            tool_revision=1,
            parameters=params,
            parameters_sha256=digest(params),
            policy_revision=policy.revision,
            status="approved",
        )
        db.add(action)
        db.flush()
        db.add(
            ActionGrant(
                action_id=action.id,
                parameters_sha256=action.parameters_sha256,
                tool_revision=1,
                policy_revision=policy.revision,
                expires=time.time() + 300,
            )
        )
        db.commit()
        aid, pid = action.id, profile.id
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: execute_write(factory, cfg, aid), range(2)))
        assert len(effects) == 1 and all(
            r["status"] in {"dispatching", "succeeded"} for r in results
        )
        assert execute_write(factory, cfg, aid)["status"] == "succeeded" and len(effects) == 1
    finally:
        with factory() as db:
            for model, identity in [
                (ActionReceipt, aid),
                (IntegrationWriteAudit, aid),
                (ActionGrant, aid),
                (ActionIntent, aid),
                (Integration, pid),
            ]:
                row = db.get(model, identity)
                if row:
                    db.delete(row)
                    db.flush()
            policy = db.get(ActionPolicy, 1)
            policy.paused, policy.revision = prior
            db.commit()


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG required")
def test_local_draft_creation_uses_valid_postgres_purpose(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hub.auth import require_session
    from hub.db import Conversation, Run
    from hub.integration_write_drafts import install_draft_api
    from hub.integrations import IntegrationWriteDraft

    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only disposable loopback hub_ci allowed")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    key = tmp_path / "draft-key"
    key.write_text(base64.b64encode(b"d" * 32).decode())
    key.chmod(0o600)
    cfg = Settings(database_url=url, secrets_key_file=str(key), integration_targets_enabled=True)
    factory = session_factory(url)
    queued = []
    monkeypatch.setattr("hub.jobs.enqueue", lambda db, cfg, rid: queued.append(rid))
    monkeypatch.setattr("hub.integration_write_drafts.start_development", lambda *a: None)
    with factory() as db:
        profile = Integration(
            name="Synthetic PG draft",
            kind="ssh",
            enabled=True,
            writes_enabled=True,
            config=encode({"kind": "ssh", "url": "synthetic.example.test", "auth": "private_key"}),
        )
        db.add(profile)
        db.commit()
        pid = profile.id
    app = FastAPI()
    app.dependency_overrides[require_session] = lambda: None
    install_draft_api(app, cfg, factory)
    identifier = None
    conversation_id = None
    run_id = None
    try:
        with TestClient(app) as client:
            r = client.post(
                "/api/integrations/" + pid + "/write-drafts",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "operation": "file.write_text",
                    "prompt": "Schreibe Test in example.txt",
                },
            )
            assert r.status_code == 200, r.text
            identifier = r.json()["id"]
            run_id = r.json()["run_id"]
            with factory() as db:
                item = db.get(IntegrationWriteDraft, identifier)
                conversation_id = item.conversation_id
                assert db.get(Conversation, conversation_id).purpose == "write_draft"
                assert db.get(Conversation, conversation_id).cloud_allowed is False
                assert json.loads(db.get(Run, run_id).context_snapshot)["model_local_only"] is True
            assert queued == [run_id]
    finally:
        with factory() as db:
            if identifier:
                db.delete(db.get(IntegrationWriteDraft, identifier))
                db.flush()
                db.get(Run, run_id).status = "cancelled"
                db.commit()
                from hub.deletion import permanently_delete

                permanently_delete(
                    db,
                    cfg,
                    "conversation",
                    conversation_id,
                    None,
                    allow_use_case=True,
                    commit=False,
                )
            db.delete(db.get(Integration, pid))
            db.commit()
