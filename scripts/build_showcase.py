"""Validate and copy only public showcase assets into the Pages upload directory."""

import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "website"
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=ROOT / ".local" / "website-build")
parser.add_argument("--revision", default="local-preview")
args = parser.parse_args()
output = args.output.resolve()
# Never replace source, runtime directories, or an arbitrary user directory.
if output != (ROOT / ".local" / "website-build").resolve():
    raise SystemExit("Output must be the dedicated .local/website-build directory")
data = json.loads((SOURCE / "project.json").read_text())
assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["updated"])
assert re.fullmatch(r"[a-f0-9]{7,40}", data["applicationCommit"])
assert data["ciUrl"].startswith("https://github.com/sschluet/obdaAI/actions/runs/")
assert len({g["id"] for g in data["groups"]}) == len(data["groups"])
for group in data["groups"]:
    assert group["features"]
    for feature in group["features"]:
        assert feature["status"] in {"live", "implemented", "limited"}
        assert feature["title"] and feature["description"]
for shot in data["screenshots"]:
    assert re.fullmatch(r"assets/[a-z]+\.png", shot["image"])
    assert (SOURCE / shot["image"]).is_file()
public_files = ["index.html", "styles.css", "app.js", "project.json", "assets/mark.svg"]
public_files += [s["image"] for s in data["screenshots"]]
public_files.append("assets/mobile.png")
if output.exists():
    shutil.rmtree(output)
for name in public_files:
    source = SOURCE / name
    assert source.is_file() and not source.is_symlink()
    destination = output / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
(output / "build.json").write_text(json.dumps({"revision": args.revision[:12]}) + "\n")
(output / ".nojekyll").touch()
print(f"Public showcase validated: {len(public_files)} files, "
      f"{sum(len(g['features']) for g in data['groups'])} features")
