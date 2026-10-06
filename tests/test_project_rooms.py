import hashlib
import uuid

import pytest
import test_knowledge
from hub.db import Source
from sqlalchemy import func, select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_knowledge.knowledge.__wrapped__(tmp_path, monkeypatch)


def test_website_snapshot_is_explicit_scoped_durable_and_idempotent(setup, monkeypatch):
    app, c, h, cfg, vault = setup
    pid = test_knowledge.project(c, h)
    foreign = test_knowledge.project(c, h, "Other project")
    calls = []

    async def page(cfg, url, approved, *, user_selected=False):
        assert approved and user_selected
        calls.append(url)
        return "Synthetic website fact: blue and seven."

    monkeypatch.setattr("hub.websearch.fetch_page", page)
    body = {
        "url": "https://example.org/evidence",
        "request_id": str(uuid.uuid4()),
        "public_url_approved": False,
    }
    assert c.post("/api/projects/" + pid + "/websites", headers=h, json=body).status_code == 403
    assert calls == []
    body["public_url_approved"] = True
    r = c.post("/api/projects/" + pid + "/websites", headers=h, json=body)
    assert r.status_code == 200, r.text
    source = r.json()
    assert test_knowledge.wait(app, source["id"]).status == "ready"
    assert (
        c.post("/api/projects/" + pid + "/websites", headers=h, json=body).json()["id"]
        == source["id"]
    )
    assert calls == [body["url"]]
    assert c.post("/api/projects/" + foreign + "/websites", headers=h, json=body).status_code == 409
    original = c.get("/api/projects/" + pid + "/sources/" + source["id"] + "/original").content
    assert (
        hashlib.sha256(original).hexdigest() == source["sha256"]
        and body["url"].encode() in original
    )
    assert c.get("/api/projects/" + pid + "/search?q=seven").json()[0]["source_id"] == source["id"]
    assert c.get("/api/projects/" + foreign + "/search?q=seven").json() == []
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Source)) == 1


def test_project_conversation_listing_never_mixes_other_rooms(setup):
    app, c, h, cfg, vault = setup
    a, b = test_knowledge.project(c, h, "A"), test_knowledge.project(c, h, "B")
    ca = c.post("/api/conversations", headers=h, json={"project_id": a}).json()["id"]
    c.post("/api/conversations", headers=h, json={"project_id": b})
    c.post("/api/conversations", headers=h, json={})
    listed = c.get("/api/conversations?project_id=" + a).json()
    assert [r["id"] for r in listed] == [ca]
    assert c.get("/api/projects/" + a).json()["name"] == "A"
    assert c.get("/api/conversations?project_id=" + str(uuid.uuid4())).status_code == 404


@pytest.mark.parametrize(
    "addresses", [["127.0.0.1"], ["169.254.169.254"], ["192.168.1.1"], ["93.184.215.14", "::1"]]
)
def test_user_selected_webpage_rejects_private_and_mixed_dns_before_http(monkeypatch, addresses):
    import asyncio

    from hub.config import Settings
    from hub.websearch import fetch_page

    monkeypatch.setattr(
        "hub.websearch.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", (ip, 443)) for ip in addresses],
    )

    def no_http(*a, **k):
        raise AssertionError("Unsafe source reached HTTP")

    monkeypatch.setattr("hub.websearch.httpx.AsyncClient", no_http)
    with pytest.raises(ValueError):
        asyncio.run(fetch_page(Settings(), "https://example.org/", True, user_selected=True))
