"""Project uploads must not turn an ordinary question into a context-size error."""

import json

import pytest
import test_knowledge
from hub.db import Message, ProviderConfig, Run
from sqlalchemy import select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_knowledge.knowledge.__wrapped__(tmp_path, monkeypatch)


def sources(app, client, headers, project_id):
    ids = []
    for index in range(3):
        blocks = [
            f"## Abschnitt {section}\nMietvertrag: Vertragsbestimmung {index}.{section}. "
            + ("Synthetische Mietregelung für diese Wohnung. " * 140)
            for section in range(5)
        ]
        content = "\n\n".join(blocks) + "\n\nDie Nettokaltmiete beträgt 780 Euro."
        source_id = test_knowledge.upload(
            client,
            headers,
            project_id,
            f"vertrag-{index}.md",
            content.encode(),
        )
        assert test_knowledge.wait(app, source_id).status == "ready"
        ids.append(source_id)
    return ids


def ask(app, client, headers, project_id, question, *, history=False):
    chat_id = client.post(
        "/api/conversations", headers=headers, json={"project_id": project_id}
    ).json()["id"]
    if history:
        with app.state.sessions() as db:
            for index in range(10):
                db.add(
                    Message(
                        conversation_id=chat_id,
                        role="assistant" if index % 2 else "user",
                        content=f"Historie {index} " + "Älterer geschützter Kontext. " * 800,
                        label="LOCAL_ONLY",
                    )
                )
            db.commit()
    response = client.post(
        f"/api/conversations/{chat_id}/messages", headers=headers, json={"content": question}
    )
    assert response.status_code == 200, response.text
    assert '"status":"succeeded"' in response.text.replace(" ", ""), response.text
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.conversation_id == chat_id))
        assert run.status == "succeeded"
        snapshot = json.loads(run.context_snapshot)
    return snapshot


@pytest.mark.parametrize("history", [False, True])
def test_many_large_source_chunks_fit_with_full_current_question(setup, history):
    app, client, headers, cfg, _ = setup
    project_id = test_knowledge.project(client, headers)
    source_ids = sources(app, client, headers, project_id)
    question = "Wie ist der Mietvertrag?"
    snapshot = ask(app, client, headers, project_id, question, history=history)
    assert any(p["content"] == question for p in snapshot["parts"])
    assert any(p["source_id"] in source_ids for p in snapshot["sources"])
    assert all(p["label"] == "LOCAL_ONLY" for p in snapshot["sources"])
    assert sum(len(p["content"].encode()) + 64 for p in snapshot["parts"]) <= cfg.context_limit
    assert app.state.providers.stream_calls == [False]
    if history:
        assert snapshot["context_window"]["omitted_message_ids"]
        assert snapshot["context_window"]["private_history_retained"]
        assert any(p["source_id"] == "history-window:private" for p in snapshot["parts"])


def test_selected_local_provider_capacity_is_honored_before_source_assembly(setup):
    app, client, headers, cfg, _ = setup
    project_id = test_knowledge.project(client, headers)
    sources(app, client, headers, project_id)
    from hub.provider_settings import seed

    with app.state.sessions() as db:
        seed(db, cfg)
        local = db.scalar(select(ProviderConfig).where(ProviderConfig.kind == "local"))
        assert local is not None
        config = json.loads(local.config)
        config.update(context_chars=12000, context_tokens=16384)
        local.config = json.dumps(config)
        db.commit()
    snapshot = ask(app, client, headers, project_id, "Wie ist der Mietvertrag?", history=True)
    capacity = snapshot["project_context_budget"]["capacity_bytes"]
    assert capacity == 11264  # 16384 tokens less the existing 4096+1024 reserves.
    assert sum(len(p["content"].encode()) + 64 for p in snapshot["parts"]) <= capacity


def test_project_web_evidence_fits_without_changing_full_research_record(setup, monkeypatch):
    from dataclasses import replace

    from hub.db import Research
    from hub.execution import execute_run
    from hub.routing import Route

    app, client, headers, _, _ = setup
    project_id = test_knowledge.project(client, headers)
    sources(app, client, headers, project_id)
    app.state.providers.decision = Route(
        capabilities=["retrieval", "web"],
        model_class="local",
        reason="fixture",
        answer=None,
    )

    async def configured_execute(factory, cfg, providers, run_id):
        await execute_run(
            factory,
            replace(cfg, search_url="http://synthetic.local/search"),
            providers,
            run_id,
        )

    records = [
        {
            "url": f"https://example.org/lease/{index}",
            "title": "Synthetic public evidence",
            "content": "Öffentliche Mietinformation. " * 100,
            "retrieved_at": 1.0,
            "provider": "searxng",
        }
        for index in range(8)
    ]

    async def search(cfg, body, *, options=None):
        assert body.query == "Wie ist der Mietvertrag?"
        return records

    monkeypatch.setattr("hub.api.execute_run", configured_execute)
    monkeypatch.setattr("hub.websearch.search", search)
    chat_id = client.post(
        "/api/conversations",
        headers=headers,
        json={"project_id": project_id},
    ).json()["id"]
    response = client.post(
        f"/api/conversations/{chat_id}/messages",
        headers=headers,
        json={"content": "Wie ist der Mietvertrag?", "web_search_allowed": True},
    )
    assert '"status":"succeeded"' in response.text.replace(" ", ""), response.text
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.conversation_id == chat_id))
        research = db.get(Research, run.id)
        assert json.loads(research.results) == records
        snapshot = json.loads(run.context_snapshot)
    budget = snapshot["project_context_budget"]
    used = sum(len(p["content"].encode()) + 64 for p in snapshot["parts"])
    assert used + budget["late_instruction_bytes"] <= budget["capacity_bytes"]
    web_parts = [p for p in snapshot["sources"] if p["source_id"].startswith(run.id + ":web:")]
    assert web_parts
    assert all(p["label"] == "LOCAL_ONLY" and p["revision"] == 1 for p in web_parts)
    assert all(p["source_id"].split(":web:")[0] == run.id for p in web_parts)
    assert len(web_parts) < 8 or any("Kontextfenster gekürzt" in p["content"] for p in web_parts)
    assert app.state.providers.stream_calls == [False]
