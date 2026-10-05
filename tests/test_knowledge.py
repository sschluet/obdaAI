import asyncio
import hashlib
import time
import uuid
import zipfile

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import Memory, Run, Source
from hub.extract import isolated_parse, parse, safe_archive
from hub.knowledge import context
from hub.memory import digest, reconcile, vault_path
from hub.routing import Route
from hub.websearch import SearchInput, search, target
from sqlalchemy import select
from test_chat import FakeProviders


@pytest.fixture
def knowledge(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "db.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = Settings(
        database_url=url,
        origin="http://testserver",
        secure_cookie=False,
        password_hash=password_hash("synthetic-knowledge-password"),
        source_dir=str(tmp_path / "sources"),
        vault_dir=str(vault),
        vault_writable=True,
    )
    app = create_app(cfg)
    app.state.providers = FakeProviders(
        Route(
            capabilities=["retrieval"],
            model_class="cloud",
            reason="synthetic source question",
            answer=None,
        )
    )
    with TestClient(app) as client:
        login = client.post(
            "/api/login",
            json={"password": "synthetic-knowledge-password"},
            headers={"Origin": "http://testserver"},
        )
        headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf"]}
        yield app, client, headers, cfg, vault


def project(client, headers, name="Synthetic project"):
    r = client.post("/api/projects", json={"name": name}, headers=headers)
    assert r.status_code == 200
    return r.json()["id"]


def upload(client, headers, pid, name, content):
    r = client.post(
        "/api/projects/" + pid + "/sources",
        content=content,
        headers={**headers, "X-File-Name": name},
    )
    assert r.status_code == 200
    return r.json()["id"]


def wait(app, sid):
    for _ in range(100):
        with app.state.sessions() as db:
            row = db.get(Source, sid)
            if row.status in {"ready", "failed"}:
                return row
        time.sleep(0.025)
    pytest.fail("Extraction did not complete")


def test_immutable_sources_scoped_retrieval_and_chat(knowledge):
    app, c, h, cfg, v = knowledge
    a, b = project(c, h, "A"), project(c, h, "B")
    sa = upload(c, h, a, "a.md", b"# invoice\nsynthetic_invoice 10 EUR")
    sb = upload(c, h, b, "b.md", b"# invoice\nsynthetic_private_other_project 500 EUR")
    assert wait(app, sa).status == wait(app, sb).status == "ready"
    found = c.get("/api/projects/" + a + "/search?q=invoice").json()
    assert found and all(x["source_id"] == sa for x in found)
    assert c.get("/api/projects/" + a + "/sources/" + sb + "/original").status_code == 404
    r = c.get("/api/projects/" + a + "/sources/" + sa + "/original")
    assert r.content == b"# invoice\nsynthetic_invoice 10 EUR"
    assert hashlib.sha256(r.content).hexdigest() == found[0]["sha256"]
    cid = c.post("/api/conversations", json={"project_id": a}, headers=h).json()["id"]
    result = c.post(
        "/api/conversations/" + cid + "/messages", json={"content": "synthetic_invoice"}, headers=h
    )
    assert "succeeded" in result.text
    assert app.state.providers.stream_calls == [False]
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.conversation_id == cid))
        assert "synthetic_invoice" in run.context_snapshot
        assert "synthetic_private_other_project" not in run.context_snapshot
    assert (
        c.post(
            "/api/conversations", json={"project_id": a, "cloud_allowed": True}, headers=h
        ).status_code
        == 409
    )


def test_decimal_table_audit(knowledge):
    app, c, h, cfg, v = knowledge
    pid = project(c, h)
    sid = upload(c, h, pid, "numbers.csv", b"Name;EUR\nA;1.234,50\nB;0,10\nFormula;=SUM(B2:B3)\n")
    assert wait(app, sid).status == "ready"
    result = c.get(f"/api/projects/{pid}/sources/{sid}/sum?column=1").json()
    assert result["total"] == "1234.60"
    assert len(result["values"]) == 2 and len(result["skipped"]) == 2
    assert all("CSV Zeile" in x["locator"] for x in result["values"])


@pytest.mark.parametrize("filename", ["../secret.md", "bad.exe", "bad.docm", "bad\\path.md"])
def test_upload_paths_types_and_csrf(knowledge, filename):
    app, c, h, cfg, v = knowledge
    pid = project(c, h)
    assert (
        c.post(
            "/api/projects/" + pid + "/sources",
            content=b"test",
            headers={**h, "X-File-Name": filename},
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/projects/" + pid + "/sources",
            content=b"test",
            headers={"X-File-Name": "safe.md", "Origin": "http://testserver"},
        ).status_code
        == 403
    )


def test_office_pdf_locators_and_formula_preservation(tmp_path):
    from docx import Document
    from openpyxl import Workbook
    from pptx import Presentation
    from pypdf import PdfReader, PdfWriter

    doc = Document()
    doc.add_heading("Synthetic heading")
    doc.add_paragraph("Synthetic paragraph")
    doc.save(tmp_path / "test.docx")
    assert any(
        "Dokumentabschnitt" in c["locator"] and "paragraph" in c["content"]
        for c in isolated_parse(tmp_path / "test.docx", ".docx")["chunks"]
    )
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Synthetic slide"
    presentation.save(tmp_path / "test.pptx")
    assert isolated_parse(tmp_path / "test.pptx", ".pptx")["chunks"][0]["locator"] == "Folie 1"
    wb = Workbook()
    wb.active.append(["Name", "Amount"])
    wb.active.append(["A", 3])
    wb.active.append(["B", "=SUM(B2)"])
    wb.save(tmp_path / "test.xlsx")
    result = isolated_parse(tmp_path / "test.xlsx", ".xlsx")
    assert (
        result["chunks"][-1]["locator"] == "Sheet!A3:B3"
        and "=SUM(B2)" in result["chunks"][-1]["content"]
    )
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("synthetic")
    writer.write(tmp_path / "locked.pdf")
    assert PdfReader(tmp_path / "locked.pdf").is_encrypted
    with pytest.raises(ValueError, match="Passwort"):
        parse(tmp_path / "locked.pdf", ".pdf")


def test_archive_active_content_and_bomb(tmp_path):
    for path in ["word/vbaProject.bin", "word/embeddings/file.exe", "../escape"]:
        archive = tmp_path / "unsafe.docx"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr(path, b"synthetic")
        with pytest.raises(ValueError):
            safe_archive(archive)
    with zipfile.ZipFile(tmp_path / "bomb.xlsx", "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("sheet", "A" * 100000)
    with pytest.raises(ValueError):
        safe_archive(tmp_path / "bomb.xlsx")


def test_vault_bidirectional_rename_delete_restart_scope(knowledge):
    app, c, h, cfg, v = knowledge
    pid = project(c, h)
    mid = str(uuid.uuid4())
    body = {"id": mid, "title": "Synthetic", "content": "memory fact", "project_id": pid}
    first = c.post("/api/memories", json=body, headers=h)
    assert first.status_code == 200
    row = first.json()
    path = v / row["path"]
    assert path.is_file()
    assert c.post("/api/memories", json=body, headers=h).json()["id"] == mid
    changed = path.read_text().replace("memory fact", "edited in Obsidian")
    path.write_text(changed)
    assert c.post("/api/memories/sync", json={}, headers=h).status_code == 200
    rows = c.get("/api/memories?project_id=" + pid).json()
    assert rows[0]["revision"] == 3 and "edited in Obsidian" in rows[0]["content"]
    assert c.get("/api/memories").json() == []
    newpath = path.with_name("renamed.md")
    path.rename(newpath)
    c.post("/api/memories/sync", json={}, headers=h)
    assert c.get("/api/memories?project_id=" + pid).json()[0]["path"].endswith("renamed.md")
    newpath.unlink()
    c.post("/api/memories/sync", json={}, headers=h)
    assert c.get("/api/memories?project_id=" + pid).json() == []
    with app.state.sessions() as db:
        reconcile(db, v)
        db.commit()
        assert db.get(Memory, mid).deleted
        assert context(db, pid, "Obsidian") == context(db, pid, "no-match")
    assert c.get("/api/memories/" + mid + "/versions").json()


def test_memory_conflict_preserves_vault_and_readonly(knowledge):
    app, c, h, cfg, v = knowledge
    mid = str(uuid.uuid4())
    body = {"id": mid, "title": "Synthetic", "content": "base"}
    row = c.post("/api/memories", json=body, headers=h).json()
    path = v / row["path"]
    path.write_text(path.read_text().replace("base", "external revision"))
    body.update(content="app conflicting revision", revision=row["revision"])
    assert c.patch("/api/memories/" + mid, json=body, headers=h).status_code == 409
    assert "external revision" in path.read_text()
    assert c.get("/api/memories").json()[0]["conflict"]
    (v / "ordinary.md").write_text("# Human note\nprivate")
    c.post("/api/memories/sync", json={}, headers=h)
    human = next(m for m in c.get("/api/memories").json() if m["path"] == "ordinary.md")
    assert not human["writable"]
    assert (
        c.patch(
            "/api/memories/" + human["id"],
            json={**body, "id": human["id"], "revision": human["revision"]},
            headers=h,
        ).status_code
        == 409
    )


def test_vault_symlink_and_path_escape(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "evil").symlink_to(tmp_path)
    for path in ["../escape", "/etc/passwd", ".obsidian/plugins/x", "evil/escape"]:
        with pytest.raises(ValueError):
            vault_path(root, path)


def test_web_private_query_blocked_before_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Private query reached DNS")

    monkeypatch.setattr("socket.getaddrinfo", fail)
    with pytest.raises(PermissionError):
        asyncio.run(
            search(Settings(), SearchInput(request_id=str(uuid.uuid4()), query="synthetic private"))
        )


def test_web_pins_and_rejects_endpoint(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 8888))]
    )
    with pytest.raises(ValueError):
        target(Settings(search_url="http://search.local/search", search_allowed_ip="127.0.0.2"))
    assert (
        target(
            Settings(search_url="http://search.local:8888/search", search_allowed_ip="127.0.0.1")
        )[0]
        == "http://127.0.0.1:8888/search"
    )


def test_memory_explicit_conflict_resolution_bound_to_digest(knowledge):
    app, c, h, cfg, vault = knowledge
    identifier = str(uuid.uuid4())
    body = {"id": identifier, "title": "Synthetic", "content": "initial"}
    row = c.post("/api/memories", json=body, headers=h).json()
    path = vault / row["path"]
    path.write_text(path.read_text().replace("initial", "external"))
    body.update(content="chosen after comparison", revision=row["revision"])
    assert c.patch("/api/memories/" + identifier, json=body, headers=h).status_code == 409
    body["resolve_vault_sha256"] = digest("# Synthetic\n\nexternal")
    result = c.patch("/api/memories/" + identifier, json=body, headers=h)
    assert result.status_code == 200 and result.json()["conflict"] == ""
    assert "chosen after comparison" in path.read_text()
    assert len(c.get("/api/memories/" + identifier + "/versions").json()) >= 3


def test_memory_crash_intent_reconciles_without_overwrite(knowledge):
    app, c, h, cfg, vault = knowledge
    mid = str(uuid.uuid4())
    with app.state.sessions() as db:
        row = Memory(
            id=mid,
            path="AI/Memory/" + mid + ".md",
            writable=True,
            content="# Pending\n\napproved",
            base_content="",
            sha256=digest("# Pending\n\napproved"),
            revision=2,
            conflict="pending:" + digest("") + ":creating",
        )
        db.add(row)
        db.commit()
        reconcile(db, vault)
        db.commit()
        assert not row.deleted and row.conflict == ""
        assert (vault / row.path).is_file()
        (vault / row.path).write_text(
            (vault / row.path).read_text().replace("approved", "external")
        )
        row.content = "# Pending\n\nnext desired"
        row.sha256 = digest(row.content)
        row.conflict = "pending:" + digest("# Pending\n\napproved")
        db.commit()
        reconcile(db, vault)
        db.commit()
        assert row.conflict == "# Pending\n\nexternal"
        assert "external" in (vault / row.path).read_text()


def test_fetch_blocks_unapproved_unlisted_and_private_dns(monkeypatch):
    from hub.websearch import fetch_page

    def forbidden(*args, **kwargs):
        pytest.fail("Forbidden fetch reached DNS")

    monkeypatch.setattr("socket.getaddrinfo", forbidden)
    with pytest.raises(PermissionError):
        asyncio.run(fetch_page(Settings(), "https://example.org/", False))
    with pytest.raises(ValueError):
        asyncio.run(fetch_page(Settings(), "https://example.org/", True))
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("169.254.169.254", 443))]
    )
    cfg = Settings(web_domains_json='["example.org"]')
    with pytest.raises(ValueError):
        asyncio.run(fetch_page(cfg, "https://example.org/", True))


def test_explicit_remember_is_local_idempotent_and_not_from_sources(knowledge):
    app, c, h, cfg, vault = knowledge
    pid = project(c, h)
    chat = c.post("/api/conversations", json={"project_id": pid}, headers=h).json()["id"]
    r = c.post(
        "/api/conversations/" + chat + "/messages",
        json={"content": "Merke dir: Synthetische Prüffarbe ist grün."},
        headers=h,
    )
    assert "Im lokalen Vault gespeichert" in r.text and "succeeded" in r.text
    with app.state.sessions() as db:
        memories = list(db.scalars(select(Memory)))
        assert len(memories) == 1 and memories[0].project_id == pid
        assert memories[0].origin.startswith("chat:") and memories[0].label == "LOCAL_ONLY"
    c.post(
        "/api/conversations/" + chat + "/retry", json={"request_id": str(uuid.uuid4())}, headers=h
    )
    with app.state.sessions() as db:
        assert len(list(db.scalars(select(Memory)))) == 1
    assert app.state.providers.calls == 0
