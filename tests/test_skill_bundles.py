"""Synthetic portable package security, immutable resources and instruction bounds."""

import io
import json
import stat
import zipfile

import pytest
from fastapi import HTTPException
from hub.db import SkillRevision
from hub.skill_api import instruction_context, parse
from hub.skill_bundles import digest, inspect_package, resolve_template
from test_skills import enable
from test_skills import setup as setup


def bundle(
    extra=None,
    front="name: synthetic-package\ndescription: Synthetic package",
    body="Use supplied master.",
):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("synthetic/SKILL.md", "---\n" + front + "\n---\n" + body)
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def office(external=False, macro=False):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        if external:
            archive.writestr(
                "_rels/.rels",
                '<Relationships><Relationship TargetMode="External" Target="https://example.invalid"/></Relationships>',
            )
        if macro:
            archive.writestr("word/vbaProject.bin", b"inert")
    return output.getvalue()


def upload(c, h, data):
    return c.post(
        "/api/skills/import-package",
        content=data,
        headers={**h, "X-File-Name": "synthetic.skill", "Content-Type": "application/octet-stream"},
    )


def test_import_download_exact_revision_and_edit_preserves_bundle(setup):
    app, c, h, _ = setup
    original = bundle(
        {
            "synthetic/assets/master.dotx": office(),
            "synthetic/scripts/helper.py": "raise RuntimeError('must never run')",
        }
    )
    response = upload(c, h, original)
    assert response.status_code == 200, response.text
    skill = response.json()
    assert not skill["enabled"] and not skill["trusted"] and not skill["cloud_allowed"]
    assert skill["bundle_sha256"] == digest(original)
    assert not skill["bundle_manifest"]["scripts_executable"]
    prefix = f"/api/skills/{skill['id']}/revisions/1"
    assert (
        c.get(prefix + "/package", headers=h, params={"sha256": digest(original)}).content
        == original
    )
    template = skill["bundle_manifest"]["templates"][0]
    params = {"path": template["path"], "sha256": template["sha256"]}
    assert c.get(prefix + "/files", headers=h, params=params).content == office()
    assert (
        c.get(prefix + "/files", headers=h, params={**params, "sha256": "0" * 64}).status_code
        == 409
    )
    from fastapi.testclient import TestClient

    with TestClient(app) as anonymous:
        assert anonymous.get(prefix + "/files", params=params).status_code == 401
    assert enable(c, h, skill).status_code == 200
    with app.state.sessions() as db:
        resolved = resolve_template(
            db, app.state.settings, skill["id"], 1, skill["bundle_sha256"], template["path"]
        )
        assert digest(resolved.read_bytes()) == template["sha256"]
    updated = c.patch(
        "/api/skills/" + skill["id"],
        headers=h,
        json={"document": skill["document"] + "\nMore detail.", "expected_revision": 1},
    ).json()
    assert updated["revision"] == 2 and updated["bundle_sha256"] == skill["bundle_sha256"]
    assert (
        c.get(prefix + "/package", headers=h, params={"sha256": digest(original)}).content
        == original
    )
    with app.state.sessions() as db:
        with pytest.raises(HTTPException):
            resolve_template(
                db, app.state.settings, skill["id"], 1, skill["bundle_sha256"], template["path"]
            )
        rev = db.get(SkillRevision, (skill["id"], 2))
        assert json.loads(rev.bundle_manifest)["templates"] == skill["bundle_manifest"]["templates"]


@pytest.mark.parametrize(
    "path", ["../bad.py", "/tmp/bad.py", "C:/bad.py", "a/../bad.py", "a\\bad.py", "a/./bad.py"]
)
def test_unsafe_paths_rejected(path):
    with pytest.raises(HTTPException):
        inspect_package(bundle({path: "inert"}))


def test_symlinks_duplicates_external_relations_and_macros_rejected():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        item = zipfile.ZipInfo("linked")
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(item, "target")
    with pytest.raises(HTTPException):
        inspect_package(output.getvalue())
    for extra in [
        {"master.dotx": office(external=True)},
        {"master.dotx": office(macro=True)},
        {"bad.docm": b"inert"},
    ]:
        with pytest.raises(HTTPException):
            inspect_package(bundle(extra))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("SKILL.md", "one")
        with pytest.warns(UserWarning):
            archive.writestr("SKILL.md", "two")
    with pytest.raises(HTTPException):
        inspect_package(output.getvalue())


def test_known_colon_metadata_normalization_preserves_original_and_long_context():
    data = bundle(
        front="name: synthetic-package\ndescription: Legacy: reproduce only",
        body=("# Rules\nFollow the master.\n" + "## Details\n" + "Text " * 7000),
    )
    document, manifest = inspect_package(data)
    meta, body = parse(document)
    assert meta.description == "Legacy: reproduce only" and manifest["warnings"]
    assert len(body) > 12000
    context = instruction_context(meta, body, manifest, "Details")
    assert len(context) <= 6000 and "Auszug" in context
    assert b"description: Legacy: reproduce only" in zipfile.ZipFile(io.BytesIO(data)).read(
        "synthetic/SKILL.md"
    )


def test_modern_dependency_requires_exact_reviewed_base_and_respects_empty_selection(setup):
    from hub.db import Conversation
    from hub.skill_api import select_skills
    from test_chat import new_chat

    app, c, h, _ = setup
    base = upload(
        c, h, bundle(front="name: avendis-praesentation\ndescription: Synthetic base")
    ).json()
    modern = upload(
        c, h, bundle(front="name: avendis-praesentation-modern\ndescription: Synthetic modern")
    ).json()
    assert enable(c, h, modern).status_code == 200
    chat = new_chat(c, h)
    with app.state.sessions() as db:
        with pytest.raises(HTTPException):
            select_skills(
                db, db.get(Conversation, chat), "/avendis-praesentation-modern create slides"
            )
    assert enable(c, h, base).status_code == 200
    with app.state.sessions() as db:
        parts, audit = select_skills(
            db, db.get(Conversation, chat), "/avendis-praesentation-modern create slides"
        )
        assert len(parts) == 2 and audit[1]["selection"] == "dependency"
        conversation = db.get(Conversation, chat)
        conversation.skill_selection = "[]"
        assert select_skills(db, conversation, "/avendis-praesentation-modern create slides") == (
            [],
            [],
        )


def test_invalid_encoding_and_file_count_are_bounded():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("SKILL.md", b"\xff")
    with pytest.raises(HTTPException):
        inspect_package(output.getvalue())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for index in range(501):
            archive.writestr(f"file-{index}.txt", b"inert")
    with pytest.raises(HTTPException) as caught:
        inspect_package(output.getvalue())
    assert caught.value.status_code == 413
