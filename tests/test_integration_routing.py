"""Automatic availability, private routing and exact shared-agent authority."""

import json
from uuid import uuid4

import pytest
from hub.agent_models import AgentJob, AgentPolicy
from hub.agent_tools import Rules
from hub.db import Message, Run
from hub.integrations import Integration
from sqlalchemy import func, select

pytest_plugins = ["test_agents"]


def add_profile(app, *, kind="mcp", name="Proton Mail", rules=None):
    rules = rules or Rules(enabled=True, max_effects=0, mcp_read_tools={"list_emails": "a" * 64})
    with app.state.sessions() as db:
        row = Integration(
            name=name,
            kind=kind,
            enabled=True,
            config=json.dumps(
                {"kind": kind, "url": "https://synthetic.example.test/mcp", "auth": "none"}
            ),
        )
        db.add(row)
        db.flush()
        db.add(
            AgentPolicy(
                integration_id=row.id, profile_revision=row.revision, rules=rules.model_dump_json()
            )
        )
        db.commit()
        return row.id


def standalone(agent):
    return agent[1].post("/api/conversations", json={}, headers=agent[2]).json()["id"]


def route(agent, chat, goal, **kwargs):
    return agent[1].post(
        f"/api/conversations/{chat}/integration-route",
        json={"goal": goal},
        headers=agent[2],
        **kwargs,
    )


@pytest.mark.parametrize(
    "goal", ["Welche neuen Mails gab es heute?", "Lies meinen Posteingang", "Show my emails"]
)
def test_mail_question_routes_without_target_model_or_state_effects(agent, monkeypatch, goal):
    app = agent[0]
    mailbox = add_profile(app)
    chat = standalone(agent)
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a, **k: pytest.fail("Routing must not resolve/connect")
    )
    with app.state.sessions() as db:
        before = [
            db.scalar(select(func.count()).select_from(model)) for model in (AgentJob, Message, Run)
        ]
    response = route(agent, chat, goal)
    assert response.status_code == 200
    assert response.json() == {"route": "agent", "integration_ids": [mailbox]}
    with app.state.sessions() as db:
        assert before == [
            db.scalar(select(func.count()).select_from(model)) for model in (AgentJob, Message, Run)
        ]


@pytest.mark.parametrize(
    "goal",
    [
        "Hallo",
        "Erkläre IMAP und Gmail",
        "Übersetze: neue Mails",
        "Wie richte ich Gmail ein?",
        "What is Proton Mail?",
        "Erstelle mir ein Word-Dokument über das Wetter",
        "Recherchiere aktuelle Linux-Distributionen",
        "Welche Neuigkeiten gibt es zu Home Assistant?",
        "Welche aktuellen Nachrichten gibt es heute aus der Ukraine?",
        "Kannst du mir ein Word-Dokument über das Wetter erstellen?",
        "A" * 16000,
    ],
)
def test_ordinary_explanation_translation_and_long_chat_do_not_enter_agent(agent, goal):
    add_profile(agent[0])
    add_profile(
        agent[0],
        kind="ssh",
        name="Linux Server",
        rules=Rules(enabled=True, file_read_roots=["/srv"]),
    )
    assert route(agent, standalone(agent), goal).json() == {"route": "chat", "integration_ids": []}


def test_named_mail_account_excludes_other_account_and_read_query_excludes_smtp(agent):
    app = agent[0]
    proton = add_profile(app)
    other = add_profile(app, name="Other Inbox")
    smtp = add_profile(
        app,
        kind="smtp",
        name="Outgoing Mail",
        rules=Rules(enabled=True, mail_recipients=["synthetic@example.test"]),
    )
    chat = standalone(agent)
    assert route(agent, chat, "Welche neuen Mails gibt es bei Proton?").json()[
        "integration_ids"
    ] == [proton]
    assert route(agent, chat, "Welche neuen Mails gab es heute?").json()[
        "integration_ids"
    ] == sorted([proton, other])
    assert smtp in route(agent, chat, "Sende eine Mail an meinen Kontakt").json()["integration_ids"]


def test_scope_off_missing_policy_stale_policy_and_disabled_target_prevent_routing(agent):
    app, client, headers = agent[:3]
    identifier = add_profile(app)
    chat = standalone(agent)
    path = f"/api/conversations/{chat}/integration-route"
    assert client.post(path, json={"goal": "Mails"}).status_code == 403
    old_cookies = dict(client.cookies)
    client.cookies.clear()
    assert client.post(path, json={"goal": "Mails"}, headers=headers).status_code == 401
    client.cookies.update(old_cookies)
    assert (
        client.post(
            path, json={"goal": "Mails"}, headers={"Origin": "http://testserver"}
        ).status_code
        == 403
    )
    with app.state.sessions() as db:
        policy = db.get(AgentPolicy, identifier)
        policy.profile_revision += 1
        db.commit()
    assert route(agent, chat, "Mails").json()["route"] == "chat"
    with app.state.sessions() as db:
        db.get(AgentPolicy, identifier).profile_revision = 1
        db.get(Integration, identifier).enabled = False
        db.commit()
    assert route(agent, chat, "Mails").json()["route"] == "chat"
    client.put(
        f"/api/integration-bindings/conversation/{chat}",
        json={"expected_revision": 0, "integration_ids": [], "selection_mode": "off"},
        headers=headers,
    )
    assert route(agent, chat, "Mails").json()["route"] == "chat"


def test_concrete_subset_keeps_unrelated_readonly_mail_budget_out_of_write_job(agent):
    app, client, headers = agent[:3]
    add_profile(app)
    chat = standalone(agent)
    body = {
        "request_id": str(uuid4()),
        "goal": "Ändere das Dokument im Archiv",
        "integration_ids": [agent[4]],
    }
    response = client.post(f"/api/conversations/{chat}/agent-runs", json=body, headers=headers)
    assert response.status_code == 200, response.text
    with app.state.sessions() as db:
        job = db.get(AgentJob, response.json()["id"])
        assert job.max_effects == 2
        assert [item["id"] for item in json.loads(job.bindings)["profiles"]] == [agent[4]]
    assert (
        client.post(
            f"/api/conversations/{chat}/agent-runs",
            json={**body, "integration_ids": [str(uuid4())]},
            headers=headers,
        ).status_code
        == 409
    )


def test_implicit_automatic_agent_start_also_narrows_to_goal_and_preserves_rules(agent):
    app, client, headers = agent[:3]
    add_profile(app)
    chat = standalone(agent)
    response = client.post(
        f"/api/conversations/{chat}/agent-runs",
        json={"request_id": str(uuid4()), "goal": "Ändere Dokument im Archiv"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    with app.state.sessions() as db:
        job = db.get(AgentJob, response.json()["id"])
        assert job.max_effects == 2
        assert [item["id"] for item in json.loads(job.bindings)["profiles"]] == [agent[4]]


@pytest.mark.parametrize("selection", ["unknown", "disabled-policy", "empty", "duplicate"])
def test_fresh_agent_requests_reject_unavailable_or_unapproved_subsets(agent, selection):
    chat = standalone(agent)
    if selection == "unknown":
        identifiers = [str(uuid4())]
    elif selection == "disabled-policy":
        identifiers = [add_profile(agent[0], rules=Rules(enabled=False))]
    elif selection == "duplicate":
        identifiers = [agent[4], agent[4]]
    else:
        identifiers = []
    response = agent[1].post(
        f"/api/conversations/{chat}/agent-runs",
        json={
            "request_id": str(uuid4()),
            "goal": "Inspect selected system",
            "integration_ids": identifiers,
        },
        headers=agent[2],
    )
    assert response.status_code == 409
    with agent[0].state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AgentJob)) == 0


def test_send_only_binds_smtp_budget_and_private_mail_office_stays_agent(agent):
    mailbox = add_profile(agent[0])
    smtp = add_profile(
        agent[0],
        kind="smtp",
        name="Outgoing Mail",
        rules=Rules(enabled=True, mail_recipients=["synthetic@example.test"], max_effects=1),
    )
    chat = standalone(agent)
    goal = "Sende eine Mail an synthetic@example.test"
    assert route(agent, chat, goal).json() == {"route": "agent", "integration_ids": [smtp]}
    assert route(agent, chat, "Erstelle eine Excel mit meinen Mails von heute").json() == {
        "route": "agent",
        "integration_ids": [mailbox],
    }
    response = agent[1].post(
        f"/api/conversations/{chat}/agent-runs",
        json={"request_id": str(uuid4()), "goal": goal, "integration_ids": [smtp]},
        headers=agent[2],
    )
    assert response.status_code == 200, response.text
    with agent[0].state.sessions() as db:
        assert db.get(AgentJob, response.json()["id"]).max_effects == 1


@pytest.mark.parametrize(
    "change", ["new-profile", "unrelated-revision", "selected-revision", "off"]
)
def test_auto_job_keeps_concrete_authority_but_respects_selected_revocation(agent, change):
    from hub import agent_runtime
    from hub.integrations import IntegrationBinding

    app, client, headers = agent[:3]
    other = add_profile(app)
    chat = standalone(agent)
    response = client.post(
        f"/api/conversations/{chat}/agent-runs",
        json={
            "request_id": str(uuid4()),
            "goal": "Ändere Dokument im Archiv",
            "integration_ids": [agent[4]],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    if change == "new-profile":
        add_profile(app, name="Newly enabled mailbox")
    with app.state.sessions() as db:
        if change == "unrelated-revision":
            db.get(Integration, other).revision += 1
        elif change == "selected-revision":
            db.get(Integration, agent[4]).revision += 1
        elif change == "off":
            db.add(
                IntegrationBinding(
                    scope="conversation", owner_id=chat, selection_mode="off", integration_ids="[]"
                )
            )
        db.commit()
        job = db.get(AgentJob, response.json()["id"])
        if change in {"selected-revision", "off"}:
            with pytest.raises(PermissionError):
                agent_runtime.gate(db, agent[3], job)
        else:
            assert set(agent_runtime.gate(db, agent[3], job)) == {agent[4]}
            assert [item["id"] for item in json.loads(job.bindings)["selection"]["bindings"]] == [
                agent[4]
            ]
    # Ordinary API submissions cannot race an active agent in this conversation.
    assert (
        client.post(
            f"/api/conversations/{chat}/messages", json={"content": "Hello"}, headers=headers
        ).status_code
        == 409
    )
