"""Synthetic OCR quality and bounded-processing contracts; no private originals."""

import subprocess
from pathlib import Path

import pytest
from hub.extract import ocr, parse
from hub.ocr_local import MAX_EDGE, MAX_PIXELS, _deskew, needs_ocr, prepare, raster_edge
from PIL import Image, ImageDraw


def test_paper_raster_is_300dpi_with_large_page_pixel_bound():
    assert raster_edge(595, 842) == 3508
    assert raster_edge(14400, 14400) ** 2 <= MAX_PIXELS
    assert raster_edge(14400, 72) <= MAX_EDGE


@pytest.mark.parametrize("text", ["", "   ", "PDF " + "\ufffd" * 20, "a\x00b\x00c"])
def test_unreadable_text_layers_need_ocr(text):
    assert needs_ocr(text, has_images=False)


def test_hybrid_title_does_not_hide_scanned_body_but_native_text_stays():
    assert needs_ocr("Mietvertrag", has_images=True)
    assert not needs_ocr("Kurzer Titel", has_images=False)
    assert not needs_ocr(
        "Dieser Vertrag umfasst die vereinbarte Miete von 700 Euro.", has_images=True
    )


def test_transparent_scan_composited_white_and_original_unchanged(tmp_path):
    source = tmp_path / "transparent.png"
    image = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((30, 80), "Mietvertrag 700 Euro", fill="black")
    image.save(source)
    original = source.read_bytes()
    target = tmp_path / "prepared.png"
    prepare(source, target)
    with Image.open(target) as result:
        assert result.mode == "L"
        assert result.getpixel((15, 15)) == 255
        assert abs(result.info["dpi"][0] - 300) < 1
    assert source.read_bytes() == original


def test_deskew_improves_text_lines_and_blank_pages_stay():
    page = Image.new("L", (500, 700), "white")
    draw = ImageDraw.Draw(page)
    for y in range(100, 600, 30):
        draw.rectangle((50, y, 440, y + 3), fill="black")
    skewed = page.rotate(2, fillcolor=255)
    corrected = _deskew(skewed)
    assert corrected.tobytes() != skewed.tobytes()
    blank = Image.new("L", (200, 300), "white")
    assert _deskew(blank) is blank


def test_tesseract_has_orientation_dpi_and_single_cpu_thread(tmp_path, monkeypatch):
    source = tmp_path / "input.png"
    Image.new("RGB", (300, 400), "white").save(source)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert Path(command[1]).is_file()
        return subprocess.CompletedProcess(command, 0, stdout=b"Synthetic German scan", stderr=b"")

    monkeypatch.setattr("hub.extract.subprocess.run", run)
    assert ocr(source, tmp_path) == "Synthetic German scan"
    command, kwargs = calls[0]
    assert command[-4:] == ["--dpi", "300", "--psm", "1"]
    assert kwargs["env"]["OMP_THREAD_LIMIT"] == "1"
    assert kwargs["env"]["OMP_NUM_THREADS"] == "1"
    assert kwargs["timeout"] == 30
    assert len(calls) == 1  # No unconditional repeated OCR passes.


def test_pdf_raster_preserves_native_text_if_ocr_is_empty(tmp_path, monkeypatch):
    from pypdf import PdfWriter

    source = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(source)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("hub.extract.subprocess.run", run)
    monkeypatch.setattr("hub.extract.ocr", lambda *args: "")
    result = parse(source, ".pdf")
    assert "Kein Text" in result["chunks"][0]["content"]
    assert calls[0][calls[0].index("-r") + 1] == "300"
    assert calls[0][calls[0].index("-scale-to") + 1] == "3508"
    assert "300 dpi" in result["notes"][0]


def test_dense_pdf_scan_uses_bounded_longer_ocr_window(tmp_path, monkeypatch):
    from hub.extract import parse
    from pypdf import PdfWriter

    source = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as stream:
        writer.write(stream)
    monkeypatch.setattr(
        "hub.extract.subprocess.run", lambda *a, **k: subprocess.CompletedProcess(a, 0)
    )
    calls = []

    def read(path, work, timeout=30):
        calls.append(timeout)
        return "Synthetischer Mietvertrag und Vertragsbedingungen"

    monkeypatch.setattr("hub.extract.ocr", read)
    result = parse(source, ".pdf")
    assert calls == [120]
    assert "Mietvertrag" in result["chunks"][0]["content"]
