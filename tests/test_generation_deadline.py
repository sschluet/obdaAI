"""Synthetic execution budgets; no provider access or private content."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from hub import execution
from hub.config import Settings
from hub.db import Message, Run, RunEvent
from hub.execution import execute_run
from hub.routing import Route
from pydantic import ValidationError
from sqlalchemy import select
from test_chat import FakeProviders, new_chat

pytest_plugins = ["test_chat"]


def queued(setup, *, cloud=False):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers, cloud=cloud)
    with app.state.sessions() as db:
        run = Run(conversation_id=chat_id, status="queued")
        db.add(run)
        db.add(
            Message(
                conversation_id=chat_id,
                role="user",
                content="Synthetic deadline test",
                label="CLOUD_ALLOWED" if cloud else "LOCAL_ONLY",
            )
        )
        db.commit()
        return chat_id, run.id


def short_budget(cfg, *, preparation=0.12, generation=0.3):
    # Production validation disallows tiny generation budgets. These isolated
    # tests compress wall-clock time without weakening the public configuration.
    cfg = replace(cfg)
    object.__setattr__(cfg, "run_timeout", preparation)
    object.__setattr__(cfg, "generation_timeout", generation)
    return cfg


@pytest.mark.parametrize("external", [False, True])
def test_answer_budget_restarts_after_preparation_and_allows_long_stream(
    setup, external, monkeypatch
):
    app, client, _, _ = setup
    chat_id, run_id = queued(setup, cloud=external)

    class VirtualDeadline:
        # Database work and CI scheduling must not consume these synthetic
        # budgets. Advance only the provider's logical preparation/stream time.
        now = 0.0

        def __init__(self, budget):
            self.when = self.now + budget
            self.rescheduled = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def reschedule(self, when):
            self.when = when
            self.rescheduled.append(when)

        async def advance(self, seconds):
            self.now += seconds
            if self.now >= self.when:
                raise TimeoutError
            await asyncio.sleep(0)

    deadline = VirtualDeadline(0.12)
    # Replace only execution's module reference, never asyncio's global clock
    # or timeout implementation used by the test client and background tasks.
    monkeypatch.setattr(
        execution,
        "asyncio",
        SimpleNamespace(
            **(
                vars(asyncio)
                | {
                    "timeout": lambda budget: deadline,
                    "get_running_loop": lambda: SimpleNamespace(time=lambda: deadline.now),
                }
            )
        ),
    )

    class Progressing(FakeProviders):
        async def route(self, parts, roles):
            await deadline.advance(0.06)
            return Route(
                capabilities=["chat"],
                model_class="cloud" if external else "local",
                reason="Synthetic route",
            )

        async def stream(self, parts, roles, *, external, grants):
            self.stream_calls.append(external)
            yield "Synthetic "
            await deadline.advance(0.08)
            yield "long "
            await deadline.advance(0.08)
            yield "answer."

    provider = Progressing()
    asyncio.run(execute_run(app.state.sessions, short_budget(app.state.settings), provider, run_id))
    detail = client.get("/api/conversations/" + chat_id).json()
    assert detail["runs"][0]["status"] == "succeeded"
    assert detail["messages"][-1]["content"] == "Synthetic long answer."
    assert provider.stream_calls == [external]
    assert deadline.rescheduled == [pytest.approx(0.36)]
    assert deadline.now == pytest.approx(0.22)
    assert deadline.now > 0.12  # The original preparation deadline would fail.


def test_generation_deadline_retains_partial_and_actual_processing(setup):
    app, client, _, _ = setup
    chat_id, run_id = queued(setup)

    class Slow(FakeProviders):
        async def stream(self, *args, **kwargs):
            yield "Synthetic partial"
            await asyncio.sleep(10)
            yield " must not appear"

    provider = Slow(Route(capabilities=["chat"], model_class="local", reason="Synthetic"))
    cfg = short_budget(replace(app.state.settings, local_model="synthetic/model"), generation=0.08)
    asyncio.run(execute_run(app.state.sessions, cfg, provider, run_id))
    detail = client.get("/api/conversations/" + chat_id).json()
    assert detail["runs"][0]["status"] == "failed"
    assert "Zeitlimit der Antworterzeugung" in detail["runs"][0]["error"]
    answer = detail["messages"][-1]
    assert answer["content"] == "Synthetic partial"
    assert answer["processing"]["model"] == "synthetic/model"
    assert answer["processing"]["status"] == "failed"
    with app.state.sessions() as db:
        error = db.scalar(
            select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.kind == "error")
        )
        assert json.loads(error.payload)["message"] == detail["runs"][0]["error"]


def test_preparation_remains_bounded_without_stream_call(setup):
    app, client, _, _ = setup
    chat_id, run_id = queued(setup)

    class SlowRouter(FakeProviders):
        async def route(self, parts, roles):
            await asyncio.sleep(10)
            return self.decision

    provider = SlowRouter()
    asyncio.run(execute_run(app.state.sessions, short_budget(app.state.settings), provider, run_id))
    detail = client.get("/api/conversations/" + chat_id).json()
    assert detail["runs"][0]["status"] == "failed"
    assert "Zeitlimit der Vorbereitung" in detail["runs"][0]["error"]
    assert "lokale Einordnung" in detail["runs"][0]["error"]
    assert provider.stream_calls == []
    assert len(detail["messages"]) == 1


@pytest.mark.parametrize("failure", ["idle", "limit"])
def test_stream_failures_are_specific_and_preserve_only_delivered_output(setup, failure):
    app, client, _, _ = setup
    chat_id, run_id = queued(setup)

    class Failing(FakeProviders):
        async def stream(self, *args, **kwargs):
            yield "Synthetic delivered text"
            if failure == "idle":
                raise httpx.ReadTimeout("PRIVATE PROVIDER BODY")
            yield "x" * 96000

    provider = Failing(Route(capabilities=["chat"], model_class="local", reason="Synthetic"))
    asyncio.run(execute_run(app.state.sessions, app.state.settings, provider, run_id))
    detail = client.get("/api/conversations/" + chat_id).json()
    assert detail["runs"][0]["status"] == ("failed" if failure == "idle" else "limited")
    answer = detail["messages"][-1]["content"]
    if failure == "idle":
        assert answer == "Synthetic delivered text"
    else:
        assert answer.startswith("Synthetic delivered text")
        assert len(answer) == 96000
        assert answer.endswith("x")
    assert ("keine Daten" if failure == "idle" else "Längengrenze") in detail["runs"][0]["error"]
    events = client.get(f"/api/runs/{run_id}/events").text
    assert "PRIVATE" not in events
    assert ("event: error" if failure == "idle" else "event: warning") in events


def test_pending_stream_cancellation_interrupts_new_budget(setup):
    app, client, _, _ = setup
    chat_id, run_id = queued(setup)
    entered = asyncio.Event()

    class Waiting(FakeProviders):
        async def stream(self, *args, **kwargs):
            yield "Synthetic partial"
            entered.set()
            await asyncio.sleep(10)

    provider = Waiting(Route(capabilities=["chat"], model_class="local", reason="Synthetic"))

    async def cancel():
        task = asyncio.create_task(
            execute_run(app.state.sessions, app.state.settings, provider, run_id)
        )
        await entered.wait()
        with app.state.sessions() as db:
            db.get(Run, run_id).cancel_requested = True
            db.commit()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(cancel())
    detail = client.get("/api/conversations/" + chat_id).json()
    assert detail["runs"][0]["status"] == "cancelled"
    assert detail["messages"][-1]["content"] == "Synthetic partial"


def test_generation_configuration_is_bounded(monkeypatch):
    assert Settings().generation_timeout == 600
    for invalid in (29, 901):
        monkeypatch.setenv("HUB_GENERATION_TIMEOUT", str(invalid))
        with pytest.raises(ValidationError):
            Settings.from_env()
    monkeypatch.setenv("HUB_GENERATION_TIMEOUT", "900")
    assert Settings.from_env().generation_timeout == 900
