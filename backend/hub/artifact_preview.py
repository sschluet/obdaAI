"""Offline renderer stage. Never infer visual acceptance from a valid ZIP file."""

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from pypdf import PdfReader


def office_pdf(path: Path, folder: Path) -> Path:
    """One fixed offline conversion, also used for PDF documents from text."""
    with tempfile.TemporaryDirectory(prefix="profile-", dir=folder) as profile:
        command = [
            "/usr/lib/libreoffice/program/soffice.bin" if sys.platform == "linux" else "soffice",
            "-env:UserInstallation=" + Path(profile).as_uri(),
            "-env:OSL_SOCKET_PATH=/run/ipc",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(folder),
            str(path),
        ]
        process = subprocess.run(command, capture_output=True, timeout=60)
        if sys.platform == "linux" and process.returncode == 81:
            process = subprocess.run(command, capture_output=True, timeout=60)
        process.check_returncode()
    pdf = folder / "artifact.pdf"
    if not pdf.is_file() or pdf.is_symlink() or not 0 < pdf.stat().st_size <= 40 * 1024 * 1024:
        raise ValueError("PDF-Konvertierung fehlt oder ist zu groß")
    return pdf


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
        if path.suffix in {".docx", ".pptx", ".xlsx"}:
            pdf = office_pdf(path, folder)
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
        used = 0
        for number in range(1, len(reader.pages) + 1):
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-scale-to",
                    "1400",
                    "-f",
                    str(number),
                    "-l",
                    str(number),
                    "-singlefile",
                    str(pdf),
                    str(folder / ("page-" + str(number))),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            used += (folder / ("page-" + str(number) + ".png")).stat().st_size
            if used > 100 * 1024 * 1024:
                raise ValueError("Vorschauen überschreiten das Gesamtgrößenlimit")
    paths = sorted(folder.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
    expected = 1 if path.suffix in {".png", ".jpeg"} else len(reader.pages)
    if len(paths) != expected:
        raise ValueError("Vorschau ist unvollständig")
    result = []
    for number, image_path in enumerate(paths, 1):
        with Image.open(image_path) as image:
            image.verify()
        image_path.chmod(0o400)
        result.append(
            {
                "page": number,
                "filename": image_path.relative_to(path.parent).as_posix(),
                "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "bytes": image_path.stat().st_size,
            }
        )
    return result
