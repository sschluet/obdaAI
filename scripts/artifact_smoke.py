"""Synthetic offline runner acceptance, not private artifacts or provider calls."""

import hashlib
import io
import json
import sys
import uuid
import zipfile
from pathlib import Path

from hub.artifact_runner import process
from PIL import Image
from pypdf import PdfWriter

requests, results = Path("/requests"), Path("/results")
plans = [
    {
        "kind": "docx",
        "title": "Synthetischer Bericht",
        "pdf_export": True,
        "sections": [
            {
                "heading": "Lokales Ergebnis",
                "paragraphs": ["Editierbares deutsches Dokument."],
                "images": [{"source": 0, "caption": "Blaues Belegbild", "width_inches": 3}],
            }
        ],
    },
    {
        "kind": "pptx",
        "title": "Synthetische Präsentation",
        "slides": [
            {"title": "Lokaler Stand", "bullets": ["Editierbare Folie", "Keine Cloud"]},
            {
                "title": ("Breite Wörter für eine lesbare deutsche Überschrift " * 3).strip(),
                "bullets": [
                    "Langer Punkt mit überprüfbaren deutschen Wörtern und lesbarem Text. " * 2
                ]
                * 5,
            },
        ],
    },
    {
        "kind": "pdf",
        "title": "Seitenauswahl",
        "pages": [{"source": 0, "page": 2, "rotation": 90}, {"source": 0, "page": 1}],
    },
    {
        "kind": "image",
        "title": "Bildcollage",
        "columns": 2,
        "tile_width": 256,
        "tile_height": 256,
        "tiles": [
            {"source": 0, "crop": [0, 0, 0.5, 1], "caption": "Dunkle Bildhälfte"},
            {"source": 0, "crop": [0.5, 0, 1, 1], "caption": "Helle Bildhälfte"},
        ],
    },
    {
        "kind": "pdf",
        "title": "Neue PDF aus Text",
        "sections": [
            {"heading": "Prüfung", "paragraphs": ["Diese PDF wurde aus lokalem Text erstellt."]}
        ],
    },
]
plans.append(
    {
        "kind": "xlsx",
        "title": "Synthetische Tabelle",
        "sheets": [
            {
                "name": "Planung",
                "columns": ["Bereich", "Betrag"],
                "rows": [["Beispiel", 1234.5], ["=not-executed", 678]],
            }
        ],
    }
)
plans.append(
    {
        "kind": "pdf",
        "title": "Synthetische Einzel-PDFs",
        "pages": [{"source": 0, "page": 2, "rotation": 90}, {"source": 0, "page": 1}],
        "split_after": [1],
    }
)


def prepare() -> None:
    for plan in plans:
        folder = requests / (str(uuid.uuid4()) + "-1")
        folder.mkdir(mode=0o700)
        sources = []
        if plan["kind"] in {"docx", "image"} or plan.get("pages"):
            source = folder / "source-0"
            if plan.get("pages"):
                writer = PdfWriter()
                writer.add_blank_page(width=200, height=300)
                writer.add_blank_page(width=300, height=400)
                writer.write(str(source))
            else:
                image = Image.new("RGBA", (512, 256), "#163976")
                image.paste("#598ce8", (256, 0, 512, 256))
                image.paste((255, 0, 0, 0), (0, 0, 128, 128))
                exif = Image.Exif()
                exif[315] = "Synthetic private author"
                image.save(
                    source, format="PNG", exif=exif, icc_profile=b"synthetic-private-profile"
                )
            sources = [
                {
                    "id": str(uuid.uuid4()),
                    "revision": 1,
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            ]
            source.chmod(0o400)
        (folder / "spec.json").write_text(json.dumps({"sources": sources, "plan": plan}))
        (folder / "spec.json").chmod(0o400)


def check() -> None:
    manifests = [json.loads((p / "manifest.json").read_text()) for p in results.iterdir()]
    assert len(manifests) == 7
    for manifest in manifests:
        assert manifest["status"] == "needs_review", manifest
        assert manifest["label"] == "LOCAL_ONLY"
        assert not manifest["preview_verified"]
    assert sorted(len(m["previews"]) for m in manifests) == [1, 1, 1, 1, 2, 2, 2]
    split = next(m for m in manifests if m.get("parts"))
    assert [(p["first_page"], p["pages"]) for p in split["parts"]] == [(1, 1), (2, 1)]
    exports = [m["pdf_export"] for m in manifests if m.get("pdf_export")]
    assert len(exports) == 1 and exports[0]["bytes"] > 0
    for folder in results.iterdir():
        package = folder / "version/artifact.zip"
        if package.exists():
            from pypdf import PdfReader

            with zipfile.ZipFile(package) as archive:
                assert archive.namelist() == ["part-1.pdf", "part-2.pdf"]
                first = PdfReader(io.BytesIO(archive.read("part-1.pdf")))
                second = PdfReader(io.BytesIO(archive.read("part-2.pdf")))
                assert len(first.pages) == len(second.pages) == 1
                assert first.pages[0].mediabox.width == 300 and first.pages[0].rotation == 90
                assert second.pages[0].mediabox.width == 200
        workbook = folder / "version/artifact.xlsx"
        if workbook.exists():
            from openpyxl import load_workbook

            book = load_workbook(workbook)
            assert book["Planung"]["B2"].value == 1234.5
            assert book["Planung"]["A3"].data_type == "s"
        document = folder / "version/artifact.docx"
        if document.exists():
            with zipfile.ZipFile(document) as archive:
                media = [n for n in archive.namelist() if n.startswith("word/media/")]
                assert len(media) == 1
                with Image.open(io.BytesIO(archive.read(media[0]))) as image:
                    assert not image.getexif() and not image.info
                    assert image.mode == "RGBA" and image.getpixel((0, 0))[3] == 0
    collage = next(
        p / "version/artifact.png"
        for p in results.iterdir()
        if (p / "version/artifact.png").exists()
    )
    with Image.open(collage) as image:
        assert image.getpixel((0, 0)) == (244, 247, 253)
    for folder in requests.iterdir():
        assert not process(folder, results), "Duplicate overwrote an immutable output"
    print(
        "Seven offline plans rendered; ten previews, native XLSX, split PDFs and Word PDF export; "
        "duplicate writes rejected"
    )


if sys.argv[1] == "prepare":
    prepare()
elif sys.argv[1] == "render":
    for folder in requests.iterdir():
        assert process(folder, results)
elif sys.argv[1] == "check":
    check()
else:
    raise ValueError("Unknown synthetic test stage")
