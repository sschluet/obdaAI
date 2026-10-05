"""Offline renderer stage. Never infer visual acceptance from a valid ZIP file."""

import hashlib
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from pypdf import PdfReader


def previews(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Artefaktdatei fehlt")
    folder = path.parent / "previews"
    if folder.exists():
        raise ValueError("Vorschauversion existiert bereits")
    folder.mkdir(mode=0o700)
    if path.suffix in {".png", ".jpeg"}:
        with Image.open(path) as image:
            ImageOps.contain(image, (1200, 1200)).save(folder / "page-1.png")
    else:
        pdf = path
        if path.suffix in {".docx", ".pptx"}:
            with tempfile.TemporaryDirectory(prefix="profile-", dir=folder) as profile:
                subprocess.run(
                    ["soffice", "-env:UserInstallation=" + Path(profile).as_uri(),
                     "--headless", "--norestore", "--convert-to", "pdf", "--outdir",
                     str(folder), str(path)],
                    check=True, capture_output=True, timeout=60,
                )
            pdf = folder / "artifact.pdf"
        elif path.suffix != ".pdf":
            raise ValueError("Vorschauformat nicht unterstützt")
        if not pdf.is_file() or pdf.is_symlink() or pdf.stat().st_size > 40 * 1024 * 1024:
            raise ValueError("PDF-Vorschau fehlt oder ist zu groß")
        reader = PdfReader(str(pdf), strict=True)
        if not 1 <= len(reader.pages) <= 100:
            raise ValueError("Vorschau überschreitet das Seitenlimit")
        for page in reader.pages:
            if not 0 < float(page.mediabox.width) <= 2400:
                raise ValueError("Vorschau überschreitet das Seitenformat")
            if not 0 < float(page.mediabox.height) <= 2400:
                raise ValueError("Vorschau überschreitet das Seitenformat")
        subprocess.run(
            ["pdftoppm", "-png", "-scale-to", "1400", str(pdf), str(folder / "page")],
            check=True, capture_output=True, timeout=60,
        )
    paths = sorted(folder.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
    expected = 1 if path.suffix in {".png", ".jpeg"} else len(reader.pages)
    if len(paths) != expected:
        raise ValueError("Vorschau ist unvollständig")
    result = []
    for number, image_path in enumerate(paths, 1):
        with Image.open(image_path) as image:
            image.verify()
        image_path.chmod(0o400)
        result.append({
            "page": number, "filename": image_path.relative_to(path.parent).as_posix(),
            "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        })
    return result
