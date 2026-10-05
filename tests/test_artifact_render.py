import hashlib
from pathlib import Path

import pytest
from docx import Document
from hub.artifact_render import render
from hub.artifact_specs import ArtifactSpec
from PIL import Image
from pptx import Presentation
from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter


def binding(path: Path) -> dict[str, object]:
    return {
        "id": "11111111-1111-4111-8111-111111111111",
        "revision": 1,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_word_is_editable_and_version_is_immutable(tmp_path: Path) -> None:
    spec = ArtifactSpec.model_validate({"plan": {
        "kind": "docx", "title": "Lokaler Bericht – Übersicht",
        "sections": [{"heading": "Ergebnis", "paragraphs": ["Überprüfbarer Inhalt."],
                      "table": [["Name", "Status"], ["Test", "Erfolgreich"]]}],
    }})
    out = tmp_path / "v1"
    manifest = render(spec, [], out)
    doc = Document(str(out / "artifact.docx"))
    assert doc.paragraphs[2].text == "Überprüfbarer Inhalt."
    assert doc.tables[0].cell(1, 1).text == "Erfolgreich"
    doc.paragraphs[2].text = "Editierbarer neuer Inhalt"
    doc.save(str(tmp_path / "edited.docx"))
    assert manifest["label"] == "LOCAL_ONLY" and not manifest["preview_verified"]
    assert manifest["sha256"] == hashlib.sha256((out / "artifact.docx").read_bytes()).hexdigest()
    before = (out / "artifact.docx").read_bytes()
    with pytest.raises(ValueError, match="existiert"):
        render(spec, [], out)
    assert (out / "artifact.docx").read_bytes() == before


def test_powerpoint_has_requested_count_and_editable_notes(tmp_path: Path) -> None:
    spec = ArtifactSpec.model_validate({"plan": {
        "kind": "pptx", "title": "Projektstand",
        "slides": [
            {"title": "Stand", "bullets": ["Eine echte Folie"], "notes": "Sprechernotiz"},
            {"title": "Nächste Schritte", "bullets": ["Weiterarbeiten", "Ergebnis prüfen"]},
        ],
    }})
    render(spec, [], tmp_path / "slides")
    deck = Presentation(str(tmp_path / "slides/artifact.pptx"))
    assert len(deck.slides) == 2
    assert "Eine echte Folie" in deck.slides[0].shapes[1].text
    assert deck.slides[0].notes_slide.notes_text_frame.text == "Sprechernotiz"
    deck.slides[0].shapes[0].text = "Geändert"
    deck.save(str(tmp_path / "edited.pptx"))
    assert Presentation(str(tmp_path / "edited.pptx")).slides[0].shapes[0].text == "Geändert"


def test_pdf_reorders_rotates_removes_and_preserves_original(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    writer = PdfWriter()
    for width in [100, 200, 300]:
        writer.add_blank_page(width=width, height=400)
    writer.add_js("app.alert('never execute');")
    writer.write(str(source))
    before = source.read_bytes()
    spec = ArtifactSpec.model_validate({"sources": [binding(source)], "plan": {
        "kind": "pdf", "title": "Ausgewählte Seiten",
        "pages": [{"source": 0, "page": 3, "rotation": 90}, {"source": 0, "page": 1}],
    }})
    render(spec, [source], tmp_path / "pdf")
    result = PdfReader(str(tmp_path / "pdf/artifact.pdf"))
    assert len(result.pages) == 2
    assert result.pages[0].mediabox.width == 300 and result.pages[0].rotation == 90
    assert result.pages[1].mediabox.width == 100
    assert "/Names" not in result.trailer["/Root"]
    assert "/OpenAction" not in result.trailer["/Root"]
    assert source.read_bytes() == before


def test_crop_collage_changes_pixels_and_strips_metadata(tmp_path: Path) -> None:
    source = tmp_path / "input.png"
    original = Image.new("RGB", (256, 128), "red")
    original.paste("blue", (128, 0, 256, 128))
    original.save(source)
    spec = ArtifactSpec.model_validate({"sources": [binding(source)], "plan": {
        "kind": "image", "title": "Zwei Ausschnitte", "columns": 2,
        "tile_width": 128, "tile_height": 128,
        "tiles": [{"source": 0, "crop": [0, 0, 0.5, 1]},
                  {"source": 0, "crop": [0.5, 0, 1, 1]}],
    }})
    render(spec, [source], tmp_path / "image")
    with Image.open(tmp_path / "image/artifact.png") as output:
        assert output.size == (256, 128)
        assert output.getpixel((64, 64)) == (255, 0, 0)
        assert output.getpixel((192, 64)) == (0, 0, 255)
        assert not output.getexif()


def test_source_drift_and_symlinks_fail_before_output(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (128, 128)).save(source)
    spec = ArtifactSpec.model_validate({"sources": [binding(source)], "plan": {
        "kind": "image", "title": "Bild", "tiles": [{"source": 0}],
    }})
    alias = tmp_path / "linked.png"
    alias.symlink_to(source)
    with pytest.raises(ValueError, match="Verknüpfte"):
        render(spec, [alias], tmp_path / "bad-link")
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="verändert"):
        render(spec, [source], tmp_path / "bad-hash")
    assert not (tmp_path / "bad-link").exists() and not (tmp_path / "bad-hash").exists()


def test_invalid_pdf_page_cleans_failed_output(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(str(source))
    spec = ArtifactSpec.model_validate({"sources": [binding(source)], "plan": {
        "kind": "pdf", "title": "PDF", "pages": [{"source": 0, "page": 2}],
    }})
    with pytest.raises(ValueError, match="existiert nicht"):
        render(spec, [source], tmp_path / "missing-page")
    assert not (tmp_path / "missing-page").exists()


@pytest.mark.parametrize("extra", ["code", "url", "path", "command", "cloud_allowed"])
def test_no_executable_or_external_plan_fields(extra: str) -> None:
    with pytest.raises(ValidationError):
        ArtifactSpec.model_validate({"plan": {"kind": "docx", "title": "Test",
            "sections": [{"heading": "Ergebnis"}], extra: "external or executable"}})


def test_structural_limits_and_local_only() -> None:
    with pytest.raises(ValidationError):
        ArtifactSpec.model_validate({"label": "CLOUD_ALLOWED", "plan": {
            "kind": "docx", "title": "Test", "sections": [{"heading": "Ergebnis"}],
        }})
    with pytest.raises(ValidationError):
        ArtifactSpec.model_validate({"plan": {"kind": "pptx", "title": "Test",
            "slides": [{"title": "Überladen", "bullets": ["x"] * 6}]}})
    with pytest.raises(ValidationError):
        ArtifactSpec.model_validate({"plan": {"kind": "docx", "title": "Test",
            "sections": [{"heading": "Tabelle", "table": [["a"], ["b", "c"]]}]}})
