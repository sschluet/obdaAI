"""Exact original-file boundaries, with synthetic documents generated at runtime."""

import asyncio
import hashlib
import io
from pathlib import Path

import pytest
from fastapi import HTTPException
from hub.db import Source
from hub.extract import MAX_BYTES, isolated_parse, parse
from sqlalchemy import select
from starlette.requests import Request
from test_knowledge import knowledge as knowledge
from test_knowledge import project


def synthetic_pdf(size: int) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (Synthetic source boundary) Tj ET")
    page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    original = output.getvalue()
    # Inert comments before startxref retain objects, offsets and the EOF trailer.
    marker = original.rfind(b"startxref")
    padding = size - len(original)
    assert padding >= 3
    result = original[:marker] + b"%" + b"x" * (padding - 2) + b"\n" + original[marker:]
    assert len(result) == size
    return result


@pytest.mark.parametrize("excess", [0, 1])
def test_source_stream_exact_40_mib_boundary(knowledge, monkeypatch, excess):
    app, client, headers, cfg, vault = knowledge
    pid = project(client, headers)
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/api/projects/{project_id}/sources"
        and "POST" in getattr(route, "methods", ())
    )
    chunks = 0
    remaining = MAX_BYTES + excess
    payload = None if excess else synthetic_pdf(MAX_BYTES)

    async def receive():
        nonlocal chunks, remaining
        chunks += 1
        amount = min(1024 * 1024, remaining)
        offset = MAX_BYTES + excess - remaining
        remaining -= amount
        chunk = payload[offset : offset + amount] if payload is not None else b"x" * amount
        return {"type": "http.request", "body": chunk, "more_body": remaining > 0}

    async def deferred_extraction(*args):
        return None

    monkeypatch.setattr("hub.knowledge_api.extract_source", deferred_extraction)
    request = Request({"type": "http", "headers": [(b"x-file-name", b"synthetic.pdf")]}, receive)
    if excess:
        with pytest.raises(HTTPException) as error:
            asyncio.run(endpoint(pid, request, None))
        assert error.value.status_code == 413
        assert error.value.detail == "Maximal 40 MiB pro Datei"
    else:
        result = asyncio.run(endpoint(pid, request, None))
        assert result["size"] == MAX_BYTES
    assert chunks == 40 + excess
    with app.state.sessions() as db:
        sources = list(db.scalars(select(Source).where(Source.project_id == pid)))
        assert len(sources) == (0 if excess else 1)
        if sources:
            assert sources[0].size == MAX_BYTES
            assert sources[0].sha256 == hashlib.sha256(payload).hexdigest()


def test_real_isolated_pdf_at_40_mib_still_extracts_text(tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(synthetic_pdf(MAX_BYTES))
    result = isolated_parse(path, ".pdf")
    assert result["chunks"][0]["locator"] == "PDF Seite 1"
    assert "Synthetic source boundary" in result["chunks"][0]["content"]


def test_parser_rejects_original_one_byte_over_40_mib_before_reading(tmp_path):
    path: Path = tmp_path / "too-large.pdf"
    with path.open("wb") as output:
        output.truncate(MAX_BYTES + 1)
    with pytest.raises(ValueError, match="Dateigröße"):
        parse(path, ".pdf")
