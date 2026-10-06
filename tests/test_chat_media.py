"""Explicit original selection, real pixel/page operations, and immutable review gates."""

import hashlib
import io
import json

import pytest
import test_artifact_api
from hub.artifact_render import render
from hub.artifact_specs import ArtifactSpec
from hub.chat_artifacts import media_operation, named_originals
from hub.db import ArtifactRevision, Source, SourceChunk
from hub.knowledge import original, store
from PIL import Image
from pypdf import PdfReader, PdfWriter
from sqlalchemy import func, select
from test_chat_artifacts import FileProvider


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_artifact_api.setup.__wrapped__(tmp_path, monkeypatch)


def put(app, cfg, pid, name, content):
    with app.state.sessions() as db:
        row = Source(
            project_id=pid,
            name=name,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            status="ready",
        )
        db.add(row)
        db.flush()
        store(cfg, row, content)
        db.commit()
        return row.id


def conversation(c, h, pid):
    return c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]


def test_named_image_crop_uses_original_and_pixel_output_with_review_gate(setup, tmp_path):
    app, c, h, cfg, pid, _ = setup
    pic = Image.new("RGB", (200, 100), "red")
    pic.paste("blue", (100, 0, 200, 100))
    raw = io.BytesIO()
    pic.save(raw, format="PNG")
    content = raw.getvalue()
    sid = put(app, cfg, pid, "two-colours.png", content)
    with app.state.sessions() as db:
        db.add(SourceChunk(source_id=sid, locator="OCR", content="UNSELECTED_PIXEL_TEXT"))
        db.commit()
    app.state.providers = provider = FileProvider(
        json.dumps(
            {
                "title": "Rechte Hälfte",
                "tiles": [{"source": 0, "crop": [0.5, 0, 1, 1]}],
                "columns": 1,
                "tile_width": 128,
                "tile_height": 128,
                "format": "png",
            }
        )
    )
    chat = conversation(c, h, pid)
    r = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={
            "content": "Schneide two-colours.png auf die rechte Hälfte "
            "und skaliere auf 128 mal 128 Pixel."
        },
    )
    assert "succeeded" in r.text, r.text
    row = c.get("/api/projects/" + pid + "/artifacts").json()[0]
    assert [s["id"] for s in row["spec"]["sources"]] == [sid]
    assert row["kind"] == "image" and row["draft"]["citations"] == []
    assert "UNSELECTED_PIXEL_TEXT" not in "\n".join(p.content for p in provider.parts)
    assert c.get(test_artifact_api.base(pid, row) + "/download").status_code == 409
    with app.state.sessions() as db:
        path = original(cfg, db.get(Source, sid))
        before = path.read_bytes()
    output = tmp_path / "crop-output"
    render(ArtifactSpec.model_validate(row["spec"]), [path], output)
    with Image.open(output / "artifact.png") as result:
        assert result.size == (128, 128) and result.getpixel((64, 64)) == (0, 0, 255)
    assert path.read_bytes() == before == content


def test_named_pdf_pages_reorder_rotate_without_summarizing_original(setup, tmp_path):
    app, c, h, cfg, pid, _ = setup
    raw = io.BytesIO()
    doc = PdfWriter()
    doc.add_blank_page(width=480, height=800)
    doc.add_blank_page(width=640, height=800)
    doc.write(raw)
    content = raw.getvalue()
    sid = put(app, cfg, pid, "pages.pdf", content)
    app.state.providers = FileProvider(
        json.dumps(
            {
                "title": "Auswahl",
                "pages": [
                    {"source": 0, "page": 2, "rotation": 90},
                    {"source": 0, "page": 1, "rotation": 0},
                ],
            }
        )
    )
    chat = conversation(c, h, pid)
    r = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={
            "content": "Erstelle aus pages.pdf eine PDF mit Seiten 2,1. Drehe Seite 2 um 90 Grad."
        },
    )
    assert "succeeded" in r.text, r.text
    row = c.get("/api/projects/" + pid + "/artifacts").json()[0]
    assert row["spec"]["plan"].get("sections") is None and row["draft"]["citations"] == []
    with app.state.sessions() as db:
        path = original(cfg, db.get(Source, sid))
        before = path.read_bytes()
    output = tmp_path / "pdf-output"
    render(ArtifactSpec.model_validate(row["spec"]), [path], output)
    result = PdfReader(output / "artifact.pdf")
    assert len(result.pages) == 2 and result.pages[0].mediabox.width == 640
    assert result.pages[1].mediabox.width == 480 and result.pages[0].rotation == 90
    assert path.read_bytes() == before == content


def test_names_are_literal_scoped_and_duplicates_are_rejected(setup):
    app, c, h, cfg, pid, spec = setup
    foreign = c.post("/api/projects", headers=h, json={"name": "Foreign"}).json()["id"]
    put(app, cfg, foreign, "secret.png", b"not-used")
    with app.state.sessions() as db:
        assert named_originals(db, pid, "Crop secret.png") == []
        assert named_originals(db, pid, "Crop prefix-synthetic.png") == []
        selected = named_originals(db, pid, "Crop synthetic.png")
        assert [s.id for s in selected] == [spec["sources"][0]["id"]]
        assert media_operation("Welche Größe hat synthetic.png?", selected) is None
    put(app, cfg, pid, "synthetic.png", b"another immutable original")
    with app.state.sessions() as db:
        with pytest.raises(ValueError, match="mehrdeutig"):
            named_originals(db, pid, "Crop synthetic.png")
        assert db.scalar(select(func.count()).select_from(ArtifactRevision)) == 0


@pytest.mark.parametrize(
    "plan",
    [
        {"title": "bad", "tiles": [{"source": 3}]},
        {"title": "bad", "tiles": [{"source": 0, "crop": [0, 0, 2, 1]}]},
        {"title": "bad", "tiles": [{"source": 0}], "command": "shell"},
    ],
)
def test_invalid_model_transform_creates_no_file(setup, plan):
    app, c, h, cfg, pid, _ = setup
    app.state.providers = FileProvider(json.dumps(plan))
    chat = conversation(c, h, pid)
    c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Erstelle eine Collage aus synthetic.png."},
    )
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ArtifactRevision)) == 0
    assert c.get("/api/conversations/" + chat).json()["runs"][0]["status"] == "failed"


def test_chat_image_revision_keeps_original_bindings_and_previous_plan(setup):
    app, c, h, cfg, pid, source_spec = setup
    plan = {
        "title": "Original collage",
        "tiles": [{"source": 0}],
        "columns": 1,
        "tile_width": 256,
        "tile_height": 256,
        "format": "png",
    }
    provider = FileProvider(json.dumps(plan))
    app.state.providers = provider
    chat = conversation(c, h, pid)
    first = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Erstelle eine Collage aus synthetic.png."},
    )
    assert "succeeded" in first.text, first.text
    before = c.get("/api/projects/" + pid + "/artifacts").json()[0]
    provider.output = json.dumps(plan | {"tile_width": 128, "tile_height": 128})
    follow = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Verkleinere die letzte Datei auf 128 mal 128 Pixel."},
    )
    assert "succeeded" in follow.text, follow.text
    rows = c.get("/api/projects/" + pid + "/artifacts").json()
    old = next(r for r in rows if r["revision"] == 1)
    new = next(r for r in rows if r["revision"] == 2)
    assert old["spec"] == before["spec"] and old["spec_sha256"] == before["spec_sha256"]
    assert (
        new["artifact_id"] == old["artifact_id"]
        and new["spec"]["sources"] == source_spec["sources"]
    )
    assert new["draft"]["base"]["revision"] == 1
    assert c.get(test_artifact_api.base(pid, new) + "/download").status_code == 409


def test_source_bound_single_slide_preserves_other_slide_and_notes(setup):
    app, c, h, cfg, pid, source_spec = setup
    sid = source_spec["sources"][0]["id"]
    with app.state.sessions() as db:
        db.add(
            SourceChunk(source_id=sid, locator="Synthetic evidence", content="Blue source fact.")
        )
        db.commit()
    plan = {
        "title": "Sources presentation",
        "slides": [
            {"title": "Keep", "bullets": ["Blue."], "notes": "Keep notes"},
            {
                "title": "Shorten",
                "bullets": ["A longer blue source description."],
                "notes": "Second notes",
            },
        ],
    }
    provider = FileProvider(json.dumps(plan))
    app.state.providers = provider
    chat = conversation(c, h, pid)
    first = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Erstelle aus den Projektunterlagen eine PowerPoint mit zwei Folien."},
    )
    assert "succeeded" in first.text, first.text
    old = c.get("/api/projects/" + pid + "/artifacts").json()[0]
    revised = json.loads(json.dumps(old["spec"]["plan"]))
    revised.pop("kind")
    revised["slides"][1]["bullets"] = ["Blue."]
    revised["slides"][1]["notes"] = "Second notes"
    provider.output = json.dumps(revised)
    follow = c.post(
        "/api/conversations/" + chat + "/messages", headers=h, json={"content": "Kürze Folie 2."}
    )
    assert "succeeded" in follow.text, follow.text
    new = next(r for r in c.get("/api/projects/" + pid + "/artifacts").json() if r["revision"] == 2)
    assert new["spec"]["plan"]["slides"][0] == old["spec"]["plan"]["slides"][0]
    assert new["spec"]["sources"] == old["spec"]["sources"] and new["draft"]["target_slide"] == 2
    assert "Verwendete Auszüge:" in new["spec"]["plan"]["slides"][1]["notes"]


def test_single_original_one_based_model_index_is_unambiguous_and_audited(setup):
    app, c, h, cfg, pid, _ = setup
    app.state.providers = FileProvider(
        json.dumps({"title": "Index repair", "tiles": [{"source": 1}]})
    )
    chat = conversation(c, h, pid)
    result = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Erstelle eine Collage aus synthetic.png."},
    )
    assert "succeeded" in result.text, result.text
    row = c.get("/api/projects/" + pid + "/artifacts").json()[0]
    assert row["spec"]["plan"]["tiles"][0]["source"] == 0
    assert row["draft"]["syntax_repair"] == "single_source_one_based"


def test_single_original_is_server_bound_without_model_file_selection(setup):
    app, c, h, cfg, pid, _ = setup
    provider = FileProvider(
        json.dumps({"title": "Server binding", "tiles": [{"crop": [0, 0, 1, 1]}]})
    )
    app.state.providers = provider
    chat = conversation(c, h, pid)
    result = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Erstelle eine Collage aus synthetic.png."},
    )
    assert "succeeded" in result.text, result.text
    row = c.get("/api/projects/" + pid + "/artifacts").json()[0]
    assert row["spec"]["plan"]["tiles"][0]["source"] == 0
    assert "Exactly ONE original" in provider.parts[0].content


def test_user_page_order_overrides_model_reordering_with_audited_command_binding(setup):
    app, c, h, cfg, pid, _ = setup
    raw = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=200)
    writer.add_blank_page(width=300, height=200)
    writer.write(raw)
    put(app, cfg, pid, "ordered.pdf", raw.getvalue())
    app.state.providers = FileProvider(
        json.dumps({"title": "Order", "pages": [{"page": 1}, {"page": 2}]})
    )
    chat = conversation(c, h, pid)
    result = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Erstelle PDF mit Seiten 2,1 aus ordered.pdf."},
    )
    assert "succeeded" in result.text, result.text
    row = c.get("/api/projects/" + pid + "/artifacts").json()[0]
    assert [p["page"] for p in row["spec"]["plan"]["pages"]] == [2, 1]
    assert row["draft"]["command_binding"]["version"] == 1
