"""Disposable PostgreSQL: two dispatchers produce one remote effect."""

import base64
import concurrent.futures
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
