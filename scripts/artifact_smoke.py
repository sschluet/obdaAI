"""Synthetic offline runner acceptance, not private artifacts or provider calls."""

import hashlib
import json
import sys
import uuid
from pathlib import Path

from hub.artifact_runner import process
from PIL import Image
from pypdf import PdfWriter

requests, results = Path("/requests"), Path("/results")
plans = [
    {"kind": "docx", "title": "Synthetischer Bericht", "sections": [
        {"heading": "Lokales Ergebnis", "paragraphs": ["Editierbares deutsches Dokument."]}]},
    {"kind": "pptx", "title": "Synthetische Präsentation", "slides": [
        {"title": "Lokaler Stand", "bullets": ["Editierbare Folie", "Keine Cloud"]},
        {"title": "Abnahme", "bullets": ["Vorschau und Original geprüft"]}]},
    {"kind": "pdf", "title": "Seitenauswahl", "pages": [
        {"source": 0, "page": 2, "rotation": 90}, {"source": 0, "page": 1}]},
    {"kind": "image", "title": "Bildcollage", "columns": 2,
     "tile_width": 256, "tile_height": 256, "tiles": [
         {"source": 0, "crop": [0, 0, 0.5, 1]},
         {"source": 0, "crop": [0.5, 0, 1, 1]}]},
]


def prepare() -> None:
    for plan in plans:
        folder = requests / (str(uuid.uuid4()) + "-1")
        folder.mkdir(mode=0o700)
        sources = []
        if plan["kind"] in {"pdf", "image"}:
            source = folder / "source-0"
            if plan["kind"] == "pdf":
                writer = PdfWriter()
                writer.add_blank_page(width=200, height=300)
                writer.add_blank_page(width=300, height=400)
                writer.write(str(source))
            else:
                image = Image.new("RGB", (512, 256), "#163976")
                image.paste("#598ce8", (256, 0, 512, 256))
                image.save(source, format="PNG")
            sources = [{"id": str(uuid.uuid4()), "revision": 1,
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]
            source.chmod(0o400)
        (folder / "spec.json").write_text(json.dumps({"sources": sources, "plan": plan}))
        (folder / "spec.json").chmod(0o400)


def check() -> None:
    manifests = [json.loads((p / "manifest.json").read_text()) for p in results.iterdir()]
    assert len(manifests) == 4
    for manifest in manifests:
        assert manifest["status"] == "needs_review", manifest
        assert manifest["label"] == "LOCAL_ONLY"
        assert not manifest["preview_verified"]
    assert sorted(len(m["previews"]) for m in manifests) == [1, 1, 2, 2]
    for folder in requests.iterdir():
        assert not process(folder, results), "Duplicate overwrote an immutable output"
    print("Four offline formats rendered; six previews; duplicate writes rejected")


if sys.argv[1] == "prepare":
    prepare()
elif sys.argv[1] == "render":
    for folder in requests.iterdir():
        assert process(folder, results)
elif sys.argv[1] == "check":
    check()
else:
    raise ValueError("Unknown synthetic test stage")
