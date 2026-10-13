"""Bounded local scan preparation; original documents are never rewritten."""

import math
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

MAX_PIXELS = 12_000_000
MAX_EDGE = 5000
DPI = 300


def raster_edge(width_points: float, height_points: float) -> int:
    """300 dpi for ordinary paper; unusually large pages stay within pixel limits."""
    width = max(1.0, abs(width_points)) * DPI / 72
    height = max(1.0, abs(height_points)) * DPI / 72
    scale = min(1.0, MAX_EDGE / max(width, height), math.sqrt(MAX_PIXELS / (width * height)))
    return max(1, math.floor(max(width, height) * scale))


def _deskew(image: Image.Image) -> Image.Image:
    # Estimate horizontal text-line alignment on a tiny copy, never on the full
    # scan. A substantial improvement is required so photographs/tables are not
    # rotated based on weak evidence. Tesseract handles right-angle orientation.
    probe = image.copy()
    probe.thumbnail((500, 700))
    ink = probe.point(lambda pixel: 255 if pixel < 160 else 0)

    def score(angle: float) -> float:
        candidate = ink.rotate(angle, resample=Image.Resampling.NEAREST, fillcolor=0)
        pixels = candidate.tobytes()
        width = candidate.width
        rows = [sum(pixels[i : i + width]) / 255 for i in range(0, len(pixels), width)]
        return sum((rows[i] - rows[i - 1]) ** 2 for i in range(1, len(rows)))

    baseline = score(0)
    if baseline == 0:
        return image
    best = max((score(step / 2), step / 2) for step in range(-6, 7))
    if abs(best[1]) >= 0.5 and best[0] > baseline * 1.3:
        return image.rotate(best[1], resample=Image.Resampling.BICUBIC, fillcolor=255)
    return image


def prepare(path: Path, target: Path) -> None:
    Image.MAX_IMAGE_PIXELS = 20_000_000
    with Image.open(path) as original:
        if original.width * original.height > 20_000_000:
            raise ValueError("Bild-Pixellimit überschritten")
        image = ImageOps.exif_transpose(original)
        # Explicit white compositing preserves text in transparent scans.
        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
            rgba = image.convert("RGBA")
            white = Image.new("RGBA", rgba.size, "white")
            white.alpha_composite(rgba)
            image = white.convert("L")
        else:
            image = image.convert("L")
        scale = min(1.0, MAX_EDGE / max(image.size), math.sqrt(MAX_PIXELS / math.prod(image.size)))
        if scale < 1:
            image = image.resize(
                (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                Image.Resampling.LANCZOS,
            )
        # Normalize only strong dark backgrounds, without aggressive thresholding
        # that could erase thin letters, stamps or table borders.
        if ImageStat.Stat(image).mean[0] < 90:
            image = ImageOps.invert(image)
        image = ImageOps.autocontrast(image, cutoff=0.5)
        image = _deskew(image)
        image = ImageOps.expand(image, border=10, fill=255)
        image.save(target, dpi=(DPI, DPI))


def needs_ocr(text: str, *, has_images: bool) -> bool:
    if not text.strip():
        return True
    printable = sum(character.isprintable() or character.isspace() for character in text)
    replacement = text.count("\ufffd") + text.count("\x00")
    letters = sum(character.isalnum() for character in text)
    return (
        replacement > max(2, len(text) * 0.02)
        or printable < len(text) * 0.9
        or (has_images and letters < 40)
    )
