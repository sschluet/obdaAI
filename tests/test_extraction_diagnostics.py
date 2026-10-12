"""Offline extraction failures stay bounded and bound to their immutable original."""

import asyncio
import hashlib
import json
import subprocess
import uuid
from dataclasses import replace

import pytest
from hub.db import Source
from hub.extract import isolated_parse
from hub.extraction_errors import ExtractionError
from hub.source_runner import process
from pypdf import PdfWriter
from test_knowledge import knowledge, project, upload, wait  # noqa: F401, F811


@pytest.mark.parametrize("suffix, expected", [(".pdf", 600), (".txt", 120)])
def test_subprocess_wall_limits_and_no_secret_environment(tmp_path, monkeypatch, suffix, expected):
    path = tmp_path / "original"
    path.write_bytes(b"synthetic")

    def run(*args, **kwargs):
        assert kwargs["timeout"] == expected
        assert set(kwargs["env"]) == {
            "PATH",
            "PYTHONDONTWRITEBYTECODE",
            "HUB_PARSER_WORKDIR",
            "TMPDIR",
            "HOME",
        }
        raise subprocess.TimeoutExpired(args[0], expected, stderr=b"PRIVATE_DOCUMENT_TEXT")

    monkeypatch.setattr("hub.extract.subprocess.run", run)
    with pytest.raises(ExtractionError) as failure:
        isolated_parse(path, suffix)
    assert failure.value.code == "PARSER_TIMEOUT"
    assert "PRIVATE_DOCUMENT_TEXT" not in str(failure.value)


@pytest.mark.parametrize(
    "output, code, returncode",
    [
        (b'{"error":"PDF_ENCRYPTED"}', "PDF_ENCRYPTED", 0),
        (b'{"error":"PRIVATE_DOCUMENT_TEXT"}', "EXTRACTION_FAILED", 0),
        (b'{"error":[]}', "EXTRACTION_FAILED", 0),
        (b"[]", "EXTRACTION_FAILED", 0),
        (b"not json PRIVATE_DOCUMENT_TEXT", "EXTRACTION_FAILED", 0),
        (b'{"chunks":[{"content":"private"}],"notes":[]}', "EXTRACTION_FAILED", 0),
        (b"", "PARSER_RESOURCE_LIMIT", -9),
        (b"", "EXTRACTION_FAILED", 1),
    ],
)
def test_child_failures_are_allowlisted(tmp_path, monkeypatch, output, code, returncode):
    path = tmp_path / "original"
    path.write_bytes(b"synthetic")
    monkeypatch.setattr(
        "hub.extract.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, returncode, output, b"PRIVATE_DOCUMENT_TEXT"
        ),
    )
    with pytest.raises(ExtractionError) as failure:
        isolated_parse(path, ".pdf")
    assert failure.value.code == code
    assert "PRIVATE_DOCUMENT_TEXT" not in str(failure.value)


def test_encrypted_and_invalid_pdf_have_safe_inband_errors(tmp_path):
    encrypted = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("synthetic-password")
    writer.write(encrypted)
    with pytest.raises(ExtractionError, match="PDF_ENCRYPTED"):
        isolated_parse(encrypted, ".pdf")
    invalid = tmp_path / "broken.pdf"
    invalid.write_bytes(b"synthetic invalid PDF private body")
    with pytest.raises(ExtractionError, match="PDF_INVALID"):
        isolated_parse(invalid, ".pdf")


def test_offline_worker_error_binds_original_and_revision(tmp_path, monkeypatch):
    root, output = tmp_path / "sources", tmp_path / "results"
    root.mkdir()
    output.mkdir()
    identifier = str(uuid.uuid4())
    content = b"synthetic immutable scan"
    digest = hashlib.sha256(content).hexdigest()
    folder = root / identifier
    folder.mkdir()
    (folder / digest).write_bytes(content)
    job = root / (identifier + ".json")
    job.write_text(
        json.dumps({"id": identifier, "sha256": digest, "suffix": ".pdf", "revision": 3})
    )

    def fail(*a):
        raise ExtractionError("OCR_RUNTIME_MISSING")

    monkeypatch.setattr("hub.source_runner.isolated_parse", fail)
    process(root, output, job)
    assert json.loads((output / (identifier + "-3.json")).read_text()) == {
        "error": "OCR_RUNTIME_MISSING",
        "sha256": digest,
        "revision": 3,
    }
    assert (folder / digest).read_bytes() == content


@pytest.mark.parametrize("matching", [True, False])
def test_result_error_diagnostic_requires_current_original(knowledge, tmp_path, matching):  # noqa: F811
    from hub.knowledge import extract_source

    app, client, headers, cfg, _ = knowledge
    pid = project(client, headers)
    sid = upload(client, headers, pid, "synthetic.txt", b"synthetic preserved original")
    assert wait(app, sid).status == "ready"
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    cfg = replace(cfg, parser_result_dir=str(result_dir))
    with app.state.sessions() as db:
        source = db.get(Source, sid)
        source.status = "pending"
        sha = source.sha256
        revision = source.revision
        db.commit()
    (result_dir / f"{sid}-{revision}.json").write_text(
        json.dumps(
            {
                "error": "PDF_ENCRYPTED",
                "sha256": sha if matching else "0" * 64,
                "revision": revision,
            }
        )
    )
    asyncio.run(extract_source(app.state.sessions, cfg, sid))
    with app.state.sessions() as db:
        source = db.get(Source, sid)
        assert source.status == "failed"
        assert source.error.startswith("[PDF_ENCRYPTED]" if matching else "[EXTRACTION_FAILED]")
    assert (
        client.get(f"/api/projects/{pid}/sources/{sid}/original").content
        == b"synthetic preserved original"
    )
