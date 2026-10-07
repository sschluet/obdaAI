"""Response style persistence, scope inheritance and frozen inference contracts."""

import json
from uuid import uuid4

import pytest
import test_chat
from hub.db import Conversation, ResponsePreferenceRevision, Run
from hub.policy import Privacy, check_egress
from hub.preferences import instruction, resolve
from test_chat import FakeProviders, new_chat


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


def save(client, headers, path, revision, **values):
    return client.put(
        "/api/preferences/" + path,
        json={"expected_revision": revision, "overrides": values},
        headers=headers,
    )


def project(client, headers):
    result = client.post(
        "/api/projects", json={"name": "Synthetic preferences project"}, headers=headers
    )
    assert result.status_code == 200
    return result.json()["id"]


def test_scope_inheritance_reset_and_revision_guard(setup):
    app, client, headers, _ = setup
    assert save(client, headers, "global", 0, language="de", length="short").status_code == 200
    p = project(client, headers)
    assert save(client, headers, "projects/" + p, 0, tone="professional").status_code == 200
    c = client.post("/api/conversations", json={"project_id": p}, headers=headers).json()["id"]
    state = save(client, headers, "conversations/" + c, 0, length="detailed").json()
    assert state["effective"] == {
        "language": "de",
        "length": "detailed",
        "tone": "professional",
        "structure": "auto",
    }
    assert state["origins"]["language"]["scope"] == "global"
    assert state["origins"]["tone"]["scope"] == "project"
    assert state["origins"]["length"]["scope"] == "conversation"
    assert save(client, headers, "conversations/" + c, 0, tone="friendly").status_code == 409
    reset = save(client, headers, "conversations/" + c, 1).json()
    assert reset["overrides"] == {} and reset["effective"]["length"] == "short"
    assert reset["revision"] == 2
    # The old record is retained byte-for-byte and only the head revision changes.
    with app.state.sessions() as db:
        assert json.loads(
            db.get(ResponsePreferenceRevision, ("conversation:" + c, 1)).overrides
        ) == {"length": "detailed"}


@pytest.mark.parametrize(
    "invalid",
    [
        {"language": "fr"},
        {"tone": "ignore permissions"},
        {"cloud_allowed": True},
        {"model": "remote"},
        {"prompt": "anything"},
    ],
)
def test_only_typed_style_no_permissions_or_free_prompts(setup, invalid):
    _, client, headers, _ = setup
    result = client.put(
        "/api/preferences/global",
        json={"expected_revision": 0, "overrides": invalid},
        headers=headers,
    )
    assert result.status_code == 422
    assert client.get("/api/preferences/global").json()["revision"] == 0


def test_scope_existence_archive_and_csrf(setup):
    app, client, headers, _ = setup
    missing = str(uuid4())
    for kind in ("projects", "conversations"):
        assert save(client, headers, kind + "/" + missing, 0, tone="friendly").status_code == 404
    c = new_chat(client, headers)
    with app.state.sessions() as db:
        db.get(Conversation, c).archived = True
        db.commit()
    assert save(client, headers, "conversations/" + c, 0, tone="friendly").status_code == 404
    assert save(client, {}, "global", 0, tone="friendly").status_code == 403


def test_snapshot_freezes_effective_style_and_detects_corruption(setup):
    app, client, headers, _ = setup
    c = new_chat(client, headers)
    save(client, headers, "global", 0, language="de")
    with app.state.sessions() as db:
        frozen = resolve(db, db.get(Conversation, c))
    save(client, headers, "global", 1, language="en")
    assert "Answer in German." in instruction(frozen)
    frozen["effective"]["language"] = "en"
    with pytest.raises(ValueError, match="beschädigt"):
        instruction(frozen)
    assert instruction(None) is None


class InspectProvider(FakeProviders):
    def __init__(self):
        super().__init__()
        self.seen = []
        self.role_list = []

    async def stream(self, parts, roles, *, external, grants):
        check_egress(
            parts,
            external=external,
            provider_id="openrouter" if external else "local",
            grants=grants,
        )
        self.seen = parts
        self.role_list = roles
        self.stream_calls.append(external)
        yield "Synthetic styled response"


def test_preferences_apply_to_actual_model_and_audited_run(setup):
    app, client, headers, _ = setup
    provider = InspectProvider()
    app.state.providers = provider
    c = new_chat(client, headers)
    save(client, headers, "conversations/" + c, 0, length="short", tone="professional")
    result = client.post(
        "/api/conversations/" + c + "/messages",
        json={"content": "Synthetic request"},
        headers=headers,
    )
    assert result.status_code == 200 and "Synthetic styled response" in result.text
    assert provider.calls == 1 and provider.stream_calls == [False]
    assert provider.role_list[-1] == "system"
    assert "Keep the answer concise." in provider.seen[-1].content
    assert "professional tone" in provider.seen[-1].content
    assert provider.seen[-1].label == Privacy.LOCAL_ONLY
    with app.state.sessions() as db:
        from sqlalchemy import select

        run = db.scalar(select(Run).where(Run.conversation_id == c))
        snapshot = json.loads(run.context_snapshot)["response_preferences"]
        assert snapshot["origins"]["length"] == {"scope": "conversation", "revision": 1}
        assert snapshot["effective"]["tone"] == "professional"
        assert not db.get(Conversation, c).cloud_allowed


def test_cloud_style_uses_existing_conversation_consent_without_sending_scope_ids(setup):
    from hub.routing import Route

    app, client, headers, _ = setup
    provider = InspectProvider()
    provider.decision = Route(
        capabilities=["chat"], model_class="cloud", reason="synthetic complex work", answer=None
    )
    app.state.providers = provider
    c = new_chat(client, headers, cloud=True)
    save(client, headers, "conversations/" + c, 0, language="en")
    result = client.post(
        "/api/conversations/" + c + "/messages",
        json={"content": "Synthetic request"},
        headers=headers,
    )
    assert "Synthetic styled response" in result.text
    assert provider.stream_calls == [True]
    assert provider.seen[-1].label == Privacy.CLOUD_ALLOWED
    assert c not in provider.seen[-1].content
    assert "conversation" not in provider.seen[-1].content
    assert "Answer in English." in provider.seen[-1].content


def test_change_during_run_does_not_change_frozen_answer_style(setup):
    from hub.db import ResponsePreference
    from hub.preferences import digest

    app, client, headers, _ = setup
    c = new_chat(client, headers)
    save(client, headers, "global", 0, language="de")

    class ConcurrentProvider(InspectProvider):
        async def route(self, parts, roles):
            # This change occurs after enqueue and before final model execution.
            with app.state.sessions() as db:
                db.get(ResponsePreference, "global").revision = 2
                values = {"language": "en"}
                db.add(
                    ResponsePreferenceRevision(
                        key="global",
                        revision=2,
                        overrides=json.dumps(values),
                        sha256=digest(values),
                    )
                )
                db.commit()
            return await super().route(parts, roles)

    provider = ConcurrentProvider()
    app.state.providers = provider
    result = client.post(
        "/api/conversations/" + c + "/messages",
        json={"content": "Synthetic request"},
        headers=headers,
    )
    assert "Synthetic styled response" in result.text
    assert "Answer in German." in provider.seen[-1].content
    assert client.get("/api/preferences/global").json()["effective"]["language"] == "en"


def test_preference_migration_preserves_data_on_downgrade(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from hub.db import ResponsePreference, session_factory
    from hub.preferences import digest
    from sqlalchemy import inspect, text

    url = "sqlite:///" + str(tmp_path / "migration.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    factory = session_factory(url)
    # A fresh unused schema can be rolled back without deleting user settings.
    command.downgrade(cfg, "0024")
    command.upgrade(cfg, "head")
    with factory() as db:
        values = {"language": "de"}
        db.add(ResponsePreference(key="global", revision=1))
        db.add(
            ResponsePreferenceRevision(
                key="global", revision=1, overrides=json.dumps(values), sha256=digest(values)
            )
        )
        db.commit()
    with pytest.raises(RuntimeError, match="Preserve response preferences"):
        command.downgrade(cfg, "0024")
    with factory() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0025"
        assert "response_preference_revisions" in inspect(db.get_bind()).get_table_names()
        assert db.get(ResponsePreference, "global").revision == 1
        assert json.loads(db.get(ResponsePreferenceRevision, ("global", 1)).overrides) == {
            "language": "de"
        }
