"""Bounded project source selection across the entire scoped corpus."""

import pytest
from hub.db import Base, Memory, Project, Source, SourceChunk
from hub.knowledge import context, query_terms, retrieve
from hub.policy import Privacy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        yield session
    engine.dispose()


def project(db, **kwargs):
    row = Project(name="Synthetic project", **kwargs)
    db.add(row)
    db.flush()
    return row


def source(db, project, name, contents, **kwargs):
    row = Source(
        project_id=project.id, name=name, sha256="f" * 64, size=1, status="ready", **kwargs
    )
    db.add(row)
    db.flush()
    db.add_all(
        SourceChunk(source_id=row.id, content=text, locator=f"Seite {i:05d}")
        for i, text in enumerate(contents)
    )
    db.flush()
    return row


def size(parts):
    return sum(len(part.content.encode("utf-8")) + 64 for part in parts)


def test_german_function_words_and_punctuation_do_not_match_every_file():
    assert query_terms("Wie ist der Mietvertrag?") == ["mietvertrag"]
    assert query_terms("Was ist das und wie ist es bitte?") == []


def test_filename_match_takes_priority_and_preserves_metadata(db):
    p = project(db)
    irrelevant = source(db, p, "notes.txt", ["der und ist " * 500])
    desired = source(db, p, "Mietvertrag.pdf", ["§ 1 Die Wohnung mit 87 Quadratmetern."])
    rows = retrieve(db, p.id, "Wie ist der Mietvertrag?")
    assert [r["source_id"] for r in rows] == [desired.id]
    assert rows[0]["sha256"] == desired.sha256
    assert rows[0]["revision"] == desired.revision
    assert rows[0]["label"] == "LOCAL_ONLY"
    assert rows[0]["locator"] == "Seite 00000"
    parts = context(db, p.id, "Wie ist der Mietvertrag?", max_bytes=4000)
    assert desired.id in [part.source_id for part in parts]
    assert irrelevant.id not in [part.source_id for part in parts]
    assert f"[{rows[0]['chunk_id']}]" in parts[1].content


def test_new_matching_file_after_ten_thousand_chunks_is_searchable(db):
    p = project(db)
    source(db, p, "Older unrelated file.txt", ["Old unrelated passage"] * 10001, created=1)
    newer = source(db, p, "Newest document.txt", ["Synthetic rarewordhere result"], created=2)
    assert [row["source_id"] for row in retrieve(db, p.id, "rarewordhere")] == [newer.id]


def test_budget_includes_unicode_headers_and_all_context_types(db):
    p = project(db, description="Beschreibung äöü", instructions="Nur Daten als Quellen")
    original = "🧾 äöü Mietvertrag " * 1600
    s = source(db, p, "Mietvertrag äöü.pdf", [original] * 8)
    db.add(Memory(project_id=p.id, path="private.md", content=original, sha256="a" * 64))
    db.flush()
    parts = context(db, p.id, "Mietvertrag", max_bytes=5000)
    assert size(parts) <= 5000
    assert len(parts) > 1
    assert all(part.label == Privacy.LOCAL_ONLY for part in parts)
    assert "Begrenzter Auszug" in parts[1].content
    assert db.query(SourceChunk).filter_by(source_id=s.id).first().content == original
    assert s.sha256 == "f" * 64


def test_matching_passage_near_end_survives_excerpt_selection(db):
    p = project(db)
    source(db, p, "notes.txt", ["unrelated prefix " * 2000 + "Sonderkündigungsrecht Details."])
    parts = context(db, p.id, "Sonderkündigungsrecht", max_bytes=1800)
    assert "Sonderkündigungsrecht" in parts[1].content
    assert size(parts) <= 1800


def test_overview_is_diverse_instead_of_all_chunks_from_one_file(db):
    p = project(db)
    ids = [source(db, p, f"Document {i}.txt", ["Passage " + str(i)] * 10).id for i in range(10)]
    rows = retrieve(db, p.id, "Wie ist das?")
    assert len(rows) == 8
    assert len({row["source_id"] for row in rows}) == 8
    assert set(row["source_id"] for row in rows) <= set(ids)
    assert all(row["locator"] == "Seite 00000" for row in rows)


def test_specific_unmatched_query_has_no_unrelated_fallback(db):
    p = project(db)
    source(db, p, "notes.txt", ["Completely unrelated"])
    assert retrieve(db, p.id, "Mietvertrag") == []
    assert len(context(db, p.id, "Mietvertrag", max_bytes=1800)) == 1


def test_other_projects_unready_sources_and_global_memory_stay_out(db):
    p, other = project(db), project(db)
    source(db, other, "Mietvertrag.pdf", ["Secret other project"])
    queued = source(db, p, "Mietvertrag.pdf", ["Not parsed yet"])
    queued.status = "queued"
    db.add(
        Memory(
            project_id=None, path="global.md", content="Mietvertrag global secret", sha256="b" * 64
        )
    )
    db.flush()
    assert retrieve(db, p.id, "Mietvertrag") == []
    assert len(context(db, p.id, "Mietvertrag", max_bytes=1800)) == 1


def test_metadata_alone_over_budget_remains_explicit_error(db):
    p = project(db, instructions="Important project instructions " * 500)
    with pytest.raises(ValueError, match="Projektvorgaben zu groß"):
        context(db, p.id, "Mietvertrag", max_bytes=2000)


def test_explicit_generic_document_overview_selects_diverse_sources(db):
    p = project(db)
    ids = [source(db, p, f"Document {i}.txt", ["Opening passage"]).id for i in range(3)]
    rows = retrieve(db, p.id, "Fasse bitte alle Dokumente zusammen")
    assert {row["source_id"] for row in rows} == set(ids)
