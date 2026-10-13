"""Generate only synthetic inputs for the project artifact UI acceptance."""

from pathlib import Path

from PIL import Image
from pypdf import PdfWriter

folder = Path(".local/browser")
folder.mkdir(parents=True, exist_ok=True)
writer = PdfWriter()
writer.add_blank_page(100, 100)
writer.add_blank_page(150, 150)
writer.write(folder / "artifact-input.pdf")
Image.new("RGB", (128, 128), "#153976").save(folder / "artifact-input.png")
