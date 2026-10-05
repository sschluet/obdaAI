"""Bounded deterministic parser subprocess. Never interpret document instructions."""

import csv
import io
import json
import resource
import subprocess
import sys
import tempfile
import warnings
import zipfile
from pathlib import Path
from typing import Any

MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT = 800_000
MAX_UNITS = 2000
EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".docx",
    ".pptx",
    ".xlsx",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
}


def safe_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > 3000 or sum(m.file_size for m in members) > 80 * 1024 * 1024:
            raise ValueError("Archivgrenze überschritten")
        for member in members:
            name = member.filename.lower()
            if (
                member.flag_bits & 1
                or member.file_size > 20 * 1024 * 1024
                or member.file_size > max(1, member.compress_size) * 200
                or ".." in Path(name).parts
                or name.startswith("/")
                or "vbaproject" in name
                or "/embeddings/" in name
                or name.endswith((".exe", ".js", ".vbs"))
            ):
                raise ValueError("Aktive, verschlüsselte oder gefährliche Archiv-Inhalte")


def ocr(path: Path, cwd: Path) -> str:
    # Fixed local binary, no model/shell/network. No language pack download.
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", "deu+eng"],
        cwd=cwd,
        capture_output=True,
        timeout=30,
        check=True,
    )
    if len(result.stdout) > MAX_TEXT:
        raise ValueError("OCR-Ausgabe zu groß")
    return result.stdout.decode("utf-8")


def parse(path: Path, suffix: str) -> dict[str, Any]:
    if suffix not in EXTENSIONS or path.stat().st_size > MAX_BYTES:
        raise ValueError("Dateityp oder Dateigröße nicht unterstützt")
    chunks: list[dict[str, str]] = []
    notes: list[str] = []

    def add(locator: str, text: str, structured: str = "") -> None:
        if (
            len(chunks) >= MAX_UNITS
            or sum(len(c["content"]) for c in chunks) + len(text) > MAX_TEXT
        ):
            raise ValueError("Extraktionsgrenze überschritten")
        if text.strip():
            chunks.append({"locator": locator[:240], "content": text, "structured": structured})

    if suffix in {".docx", ".pptx", ".xlsx"}:
        safe_archive(path)
    if suffix in {".md", ".txt"}:
        heading = "Text"
        for i, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.startswith("#"):
                heading = line.lstrip("# ")[:100]
            add(f"{heading} · Zeile {i}", line)
    elif suffix == ".csv":
        content = path.read_text(encoding="utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        for i, row in enumerate(csv.reader(io.StringIO(content), dialect), 1):
            add(f"CSV Zeile {i}", " | ".join(row), json.dumps(row, ensure_ascii=False))
    elif suffix == ".docx":
        from docx import Document

        doc = Document(str(path))
        for i, paragraph in enumerate(doc.paragraphs, 1):
            add(f"Dokumentabschnitt {i}", paragraph.text)
        for i, table in enumerate(doc.tables, 1):
            for j, row in enumerate(table.rows, 1):
                cells = [c.text for c in row.cells]
                add(f"Tabelle {i} · Zeile {j}", " | ".join(cells), json.dumps(cells))
        notes.append("Abschnitte statt Seiten; eingebettete Bilder/Diagramme nicht interpretiert")
    elif suffix == ".pptx":
        from pptx import Presentation

        for i, slide in enumerate(Presentation(str(path)).slides, 1):
            for shape in slide.shapes:
                if shape.has_text_frame:
                    add(f"Folie {i}", shape.text)
                if shape.has_table:
                    for j, row in enumerate(shape.table.rows, 1):
                        cells = [c.text for c in row.cells]
                        add(f"Folie {i} · Tabelle Zeile {j}", " | ".join(cells), json.dumps(cells))
        notes.append("Folientext und Tabellen; Bilder/Diagramme nicht interpretiert")
    elif suffix == ".xlsx":
        from openpyxl import load_workbook  # type: ignore[import-untyped]
        from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]

        wb = load_workbook(
            io.BytesIO(path.read_bytes()), read_only=True, data_only=False, keep_links=False
        )
        try:
            for sheet in wb:
                if sheet.max_row > MAX_UNITS or sheet.max_column > 200:
                    raise ValueError("Tabellenlimits überschritten")
                for i, row in enumerate(sheet.iter_rows(values_only=True), 1):
                    cells = ["" if c is None else str(c) for c in row]
                    add(
                        f"{sheet.title}!A{i}:{get_column_letter(len(cells))}{i}",
                        " | ".join(cells),
                        json.dumps(cells),
                    )
        finally:
            wb.close()
        notes.append("Formeln erhalten, nicht berechnet; keine externe Verknüpfung ausgeführt")
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise ValueError("Passwortgeschütztes PDF")
        if len(reader.pages) > 100:
            raise ValueError("PDF-Seitenlimit überschritten")
        for i, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if not text.strip():
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    subprocess.run(
                        [
                            "pdftoppm",
                            "-f",
                            str(i),
                            "-l",
                            str(i),
                            "-scale-to",
                            "2200",
                            "-singlefile",
                            "-png",
                            str(path),
                            str(target / "page"),
                        ],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                    text = ocr(target / "page.png", target)
                notes.append(f"Seite {i}: lokale OCR, Erkennung kann fehlerhaft sein")
            add(f"PDF Seite {i}", text)
    else:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = 20_000_000
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    image.convert("RGB").save(target / "image.png")
                    add("Bild · lokale OCR", ocr(target / "image.png", target))
        notes.append("Lokale OCR liest Text; keine zuverlässige Bild-/Diagrammsemantik")
    if not chunks:
        raise ValueError("Keine lesbaren Inhalte extrahiert")
    return {"chunks": chunks, "notes": list(dict.fromkeys(notes))}


def isolated_parse(path: Path, suffix: str) -> dict[str, Any]:
    # Child receives no DB URL, keys, provider configuration or inherited proxies.
    try:
        with tempfile.TemporaryDirectory(prefix="hub-parser-") as work:
            result = subprocess.run(
                [sys.executable, "-m", "hub.extract", str(path.resolve()), suffix],
                env={
                    "PATH": "/usr/bin:/bin",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "HUB_PARSER_WORKDIR": work,
                    "TMPDIR": work,
                    "HOME": work,
                },
                cwd=work,
                capture_output=True,
                timeout=120,
            )
    except subprocess.TimeoutExpired:
        raise ValueError("Extraktionszeit überschritten") from None
    if result.returncode or len(result.stdout) > 4_000_000:
        raise ValueError("Extraktion fehlgeschlagen; Format, Schutz, OCR und Limits prüfen")
    return json.loads(result.stdout)  # type: ignore[no-any-return]


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    from hub.parser_sandbox import restrict

    source = Path(sys.argv[1])
    workdir = Path(__import__("os").environ["HUB_PARSER_WORKDIR"])
    restrict(source, workdir)
    print(json.dumps(parse(source, sys.argv[2]), ensure_ascii=False))
