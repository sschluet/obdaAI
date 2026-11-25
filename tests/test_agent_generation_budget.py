"""Planner compaction must precede transport with the selected provider's budget."""

import json
from dataclasses import replace

import pytest
from hub.agent_context import AgentContextLimitError, fit
from hub.agent_generation_budget import context_limit
from hub.config import Settings
from hub.db import Project, ProviderConfig
from hub.project_models import ProjectModelError, freeze
from hub.providers import Providers
from sqlalchemy import select
from test_project_models import configured, project

pytest_plugins = ["test_provider_settings"]


def test_default_local_budget_is_used_before_compaction(managed):
    app, _, _, cfg = managed
    with app.state.sessions() as db:
        row = db.scalar(select(ProviderConfig).where(
            ProviderConfig.kind == "local", ProviderConfig.is_default.is_(True)
        ))
        assert row
        row.config = json.dumps({**json.loads(row.config), "context_chars": 4000})
        db.commit()
    # No HTTP request is made by resolving a budget.
    limit = context_limit(app.state.sessions, cfg, Providers(cfg), None)
    assert limit == 4000
    with pytest.raises(AgentContextLimitError):
        fit({"goal": "g" * 5000, "history": []}, "policy", limit)


def test_project_nondefault_budget_and_revision_are_bound(managed):
    app, _, _, cfg = managed
    provider = configured(managed)
    p = project(managed, provider)
    with app.state.sessions() as db:
        row = db.get(ProviderConfig, provider["id"])
        row.config = json.dumps({**json.loads(row.config), "context_chars": 12000})
        db.commit()
        bound = freeze(db, cfg, db.get(Project, p["id"]).id)
    assert context_limit(app.state.sessions, cfg, Providers(cfg), bound) == 12000
    with app.state.sessions() as db:
        db.get(ProviderConfig, provider["id"]).revision += 1
        db.commit()
    with pytest.raises(ProjectModelError):
        context_limit(app.state.sessions, cfg, Providers(cfg), bound)


def test_provider_budget_cannot_raise_application_limit(managed):
    app, _, _, cfg = managed
    configured(managed)
    smaller = replace(cfg, context_limit=2000)
    assert context_limit(app.state.sessions, smaller, Providers(smaller), None) <= 2000


def test_injected_adapter_uses_application_budget():
    assert context_limit(None, Settings(context_limit=3000), object(), None) == 3000



def test_selected_token_capacity_bounds_utf8_before_inference(managed):
    from hub.agent_generation_budget import context_budget

    app, _, _, cfg = managed
    with app.state.sessions() as db:
        row = db.scalar(select(ProviderConfig).where(
            ProviderConfig.kind == "local", ProviderConfig.is_default.is_(True)
        ))
        row.config = json.dumps({**json.loads(row.config), "context_tokens": 8192,
                                 "context_chars": 24000, "output_tokens": 2048})
        db.commit()
    chars, byte_limit = context_budget(app.state.sessions, cfg, Providers(cfg), None)
    assert chars == 24000 and byte_limit == 8192 - 4096 - 128 - 1024
    # A short character count alone cannot guarantee that private Unicode fits.
    with pytest.raises(AgentContextLimitError):
        fit({"goal": "漢" * 1200, "history": []}, "policy", chars, max_bytes=byte_limit)
