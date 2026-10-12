"""Cloud Office plans remain data and retain native-file provenance and cost limits."""

import asyncio
import json
import time
from dataclasses import replace

import pytest
import test_artifact_api
from hub.artifact_drafts import DraftInput, preview, verify_token
from hub.artifact_specs import ArtifactSpec
from hub.chat_artifacts import explicit_file_request
from hub.db import BudgetReservation, Conversation, Message, ProviderConfig, Run
from hub.policy import Privacy, check_egress
from hub.provider_settings import seed
from hub.providers import Providers
from sqlalchemy import select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_artifact_api.setup.__wrapped__(tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "kind,plan",
    [
        (
            "docx",
            {"title": "Blumen", "sections": [{"heading": "Pflege", "paragraphs": ["Gießen."]}]},
        ),
        ("pptx", {"title": "Blumen", "slides": [{"title": "Pflege", "bullets": ["Gießen."]}]}),
        (
            "xlsx",
            {
                "title": "Kosten",
                "sheets": [{"name": "Kosten", "columns": ["Wert"], "rows": [[10]]}],
            },
        ),
    ],
)
def test_cloud_plan_receipt_has_actual_provider_and_budget(setup, monkeypatch, kind, plan):
    app, c, h, cfg, _, _ = setup
    cfg = replace(cfg, cloud_enabled=True, openrouter_model="synthetic/cloud")
    with app.state.sessions() as db:
        chat = Conversation(cloud_allowed=True)
        db.add(chat)
        db.flush()
        run = Run(conversation_id=chat.id, status="routing", context_snapshot="{}")
        db.add(run)
        db.add(
            Message(
                conversation_id=chat.id,
                role="user",
                content="Erstelle eine Datei",
                label=Privacy.CLOUD_ALLOWED,
            )
        )
        seed(db, cfg)
        row = db.get(ProviderConfig, "openrouter-default")
        data = json.loads(row.config)
        data.update(
            model="synthetic/cloud",
            context_tokens=32768,
            context_chars=32000,
            output_tokens=2048,
            max_run_cost=0.05,
            monthly_budget=1,
            pricing={"input": 0.0000001, "output": 0.0000002, "verified_at": time.time()},
        )
        row.config = json.dumps(data)
        db.commit()
        cid, rid = chat.id, run.id

    class Cloud(Providers):
        async def stream(self, parts, roles, *, external, grants):
            assert external
            check_egress(parts, external=external, provider_id="openrouter", grants=grants)
            assert parts[-1].content == "Erstelle eine Datei"
            self.measured_cost, self.cost_basis = 0.001, "provider_reported"
            yield json.dumps(plan)

    provider = Cloud(cfg)
    monkeypatch.setattr(
        "hub.artifact_drafts.runtime_provider",
        lambda *a, **kw: (cfg, provider, {"openrouter": row}),
    )

    async def fresh(*args):
        return row

    monkeypatch.setattr("hub.artifact_drafts.fresh_cloud_prices", fresh)
    result = asyncio.run(
        preview(
            app.state.sessions,
            cfg,
            None,
            DraftInput(goal="Erstelle eine Datei", kind=kind, slide_count=1),
            provider,
            conversation_id=cid,
            cloud_run_id=rid,
            provider_kind="openrouter",
        )
    )
    assert result["provider"]["kind"] == "openrouter"
    assert result["provider"]["model"] == "synthetic/cloud"
    assert result["spec"]["label"] == "LOCAL_ONLY"
    with app.state.sessions() as db:
        receipt = verify_token(
            db,
            cfg,
            result["draft_token"],
            None,
            ArtifactSpec.model_validate(result["spec"]),
            conversation_id=cid,
        )
        assert json.loads(receipt)["provider"]["kind"] == "openrouter"
        assert db.scalar(select(BudgetReservation)).measured == 0.001
        assert db.get(Run, rid).cost == 0.001


def test_cloud_file_plan_does_not_relabel_private_sources(setup):
    app, _, _, cfg, pid, spec = setup
    with pytest.raises(ValueError, match="Private Originale"):
        asyncio.run(
            preview(
                app.state.sessions,
                cfg,
                pid,
                DraftInput(goal="Erstelle eine Datei", kind="docx", sources=spec["sources"]),
                cloud_run_id="missing",
                provider_kind="openrouter",
            )
        )


@pytest.mark.parametrize(
    "goal,expected",
    [
        ("Erstelle eine Excel-Datei für die Zahlen 10 und 20", True),
        ("Bitte erstelle eine Powerpoint Präsentation über Blumen", True),
        ("Wie funktioniert Powerpoint?", False),
        ("Erstelle eine Word Datei und sende sie per Mail", False),
    ],
)
def test_explicit_file_intent(goal, expected):
    assert explicit_file_request(goal) is expected


@pytest.mark.parametrize("private,changed_goal", [(True, False), (False, True)])
def test_cloud_authorization_rejects_private_history_and_changed_goal(setup, private, changed_goal):
    from hub.cloud_artifact_planning import authorize

    app, _, _, _, _, _ = setup
    with app.state.sessions() as db:
        chat = Conversation(cloud_allowed=True)
        db.add(chat)
        db.flush()
        run = Run(
            conversation_id=chat.id,
            status="routing",
            context_snapshot=json.dumps(
                {"parts": [{"label": "LOCAL_ONLY" if private else "CLOUD_ALLOWED"}]}
            ),
        )
        db.add(run)
        db.add(
            Message(
                conversation_id=chat.id,
                role="user",
                content="Erstelle eine Datei",
                label=Privacy.CLOUD_ALLOWED,
            )
        )
        db.commit()
        cid, rid = chat.id, run.id
    with pytest.raises(ValueError):
        authorize(
            app.state.sessions,
            rid,
            cid,
            None,
            DraftInput(
                goal="anderer Inhalt" if changed_goal else "Erstelle eine Datei", kind="docx"
            ),
            "openrouter",
        )


@pytest.mark.parametrize("status", [None, 429, 503])
def test_auto_file_transport_fallback_preserves_cloud_cost_and_records_route(
    setup, monkeypatch, status
):
    import httpx
    from hub.chat_artifacts import preview_chat

    app, _, _, cfg, _, _ = setup
    with app.state.sessions() as db:
        chat = Conversation(cloud_allowed=True)
        db.add(chat)
        db.flush()
        run = Run(
            conversation_id=chat.id,
            status="routing",
            context_snapshot="{}",
            cost=0.001,
            cost_estimate=0.003,
            cost_basis="provider_reported",
        )
        db.add(run)
        db.commit()
        cid, rid = chat.id, run.id
    calls = []
    expected = {"provider": {"kind": "local", "model": "synthetic/local"}}

    async def fake_preview(*args, **kwargs):
        calls.append(kwargs["provider_kind"])
        if len(calls) == 1:
            request = httpx.Request("POST", "https://example.invalid")
            if status is None:
                raise httpx.ConnectError("synthetic failure", request=request)
            raise httpx.HTTPStatusError(
                "synthetic failure",
                request=request,
                response=httpx.Response(status, request=request),
            )
        assert kwargs.get("cloud_run_id") is None
        return expected

    monkeypatch.setattr("hub.chat_artifacts.preview", fake_preview)
    assert (
        asyncio.run(
            preview_chat(
                app.state.sessions,
                cfg,
                rid,
                None,
                DraftInput(goal="Erstelle eine Word Datei", kind="docx"),
                None,
                research_id=None,
                conversation_id=cid,
                provider_kind="openrouter",
            )
        )
        == expected
    )
    assert calls == ["openrouter", "local"]
    with app.state.sessions() as db:
        run = db.get(Run, rid)
        assert run.cost == 0.001 and run.cost_estimate == 0.003
        assert (
            json.loads(run.context_snapshot)["artifact_planning_fallback"]["from"] == "openrouter"
        )


@pytest.mark.parametrize(
    "cloud_only,status", [(True, 503), (False, 401), (False, 403), (False, 422), (False, None)]
)
def test_file_fallback_never_bypasses_explicit_cloud_or_permission_errors(
    setup, monkeypatch, cloud_only, status
):
    import httpx
    from hub.chat_artifacts import preview_chat

    app, _, _, cfg, _, _ = setup
    with app.state.sessions() as db:
        chat = Conversation(cloud_allowed=True)
        db.add(chat)
        db.flush()
        run = Run(
            conversation_id=chat.id,
            status="routing",
            context_snapshot=json.dumps({"model_cloud_only": cloud_only}),
        )
        db.add(run)
        db.commit()
        cid, rid = chat.id, run.id
    calls = []

    async def fake_preview(*args, **kwargs):
        calls.append(kwargs["provider_kind"])
        if status is None:
            raise PermissionError("synthetic cost/privacy/filter restriction")
        request = httpx.Request("POST", "https://example.invalid")
        raise httpx.HTTPStatusError(
            "synthetic failure", request=request, response=httpx.Response(status, request=request)
        )

    monkeypatch.setattr("hub.chat_artifacts.preview", fake_preview)
    with pytest.raises((httpx.HTTPStatusError, PermissionError)):
        asyncio.run(
            preview_chat(
                app.state.sessions,
                cfg,
                rid,
                None,
                DraftInput(goal="Erstelle eine Word Datei", kind="docx"),
                None,
                research_id=None,
                conversation_id=cid,
                provider_kind="openrouter",
            )
        )
    assert calls == ["openrouter"]
    with app.state.sessions() as db:
        assert "artifact_planning_fallback" not in json.loads(db.get(Run, rid).context_snapshot)
