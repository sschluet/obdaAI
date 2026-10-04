"""Conservative source scan; gitleaks in CI supplements these checks."""

import re
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = (
    subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    )
    .decode()
    .split("\0")
)
patterns = [
    re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|sk-or-v1-[a-f0-9]{40,})\b"),
]
violations = []
for name in filter(None, files):
    p = root / name
    if p.is_symlink():
        violations.append(name)
        continue
    if any(x in p.parts for x in ("secrets", "vault", "uploads", "data", ".local")):
        violations.append(name)
        continue
    if p.name.startswith(".env") and p.name != ".env.example":
        violations.append(name)
        continue
    if p.is_file():
        text = p.read_text(errors="replace")
        if any(pattern.search(text) for pattern in patterns):
            violations.append(name)
if violations:
    print("Blocked source paths: " + ", ".join(violations))
    sys.exit(1)
print(f"Source scan passed ({len(list(filter(None, files)))} files).")
