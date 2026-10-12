"""Local model plans keep exact reviewed package/template provenance through dispatch."""

import io
import json

import pytest
from docx import Document
from hub.artifact_specs import ArtifactSpec
from hub.db import ArtifactRevision
from test_artifact_api import setup as setup
from test_artifact_drafts import DOCUMENT, DraftProvider
from test_skill_bundles import bundle


def imported(c, h):
    document = Document()
    document.sections[0].header.paragraphs[0].text = "Synthetic master header"
    document.add_paragraph("Template sample")
    output = io.BytesIO()
    document.save(output)
    package = bundle({"synthetic/assets/master.docx": output.getvalue()})
    response = c.post(
        "/api/skills/import-package", headers={**h, "X-File-Name": "test.skill"}, content=package
    )
    assert response.status_code == 200, response.text
    skill = response.json()
    response = c.post(
        "/api/skills/" + skill["id"] + "/trust",
        headers=h,
        json={"expected_revision": skill["revision"], "sha256": skill["sha256"], "enabled": True},
    )
    assert response.status_code == 200
    return skill


def propose(app, c, h, pid, skill):
    app.state.providers = DraftProvider(DOCUMENT)
    result = c.post(
        "/api/projects/" + pid + "/artifact-drafts",
        headers=h,
        json={
            "goal": "Create a synthetic Word report",
            "kind": "docx",
            "skill_bindings": [
                {"id": skill["id"], "revision": skill["revision"], "sha256": skill["sha256"]}
            ],
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_template_enters_exact_spool_and_receipt(setup):
    app, c, h, cfg, pid, _ = setup
    skill = imported(c, h)
    proposal = propose(app, c, h, pid, skill)
    template = proposal["spec"]["template"]
    assert template["bundle_sha256"] == skill["bundle_sha256"]
    import uuid

    saved = c.post(
        "/api/projects/" + pid + "/artifacts",
        headers=h,
        json={
            "request_id": str(uuid.uuid4()),
            "spec": proposal["spec"],
            "draft_token": proposal["draft_token"],
        },
    )
    assert saved.status_code == 200, saved.text
    row = saved.json()
    with app.state.sessions() as db:
        revision = db.get(ArtifactRevision, (row["artifact_id"], row["revision"]))
        assert json.loads(revision.draft_metadata)["skills"][0]["id"] == skill["id"]
    from pathlib import Path

    from hub.artifact_render import render

    spool = Path(cfg.artifact_request_dir) / (row["artifact_id"] + "-1")
    spec = ArtifactSpec.model_validate_json((spool / "spec.json").read_text())
    manifest = render(spec, [spool / "source-0"], Path(cfg.artifact_result_dir) / "direct")
    output = Document(Path(cfg.artifact_result_dir) / "direct" / manifest["filename"])
    assert output.sections[0].header.paragraphs[0].text == "Synthetic master header"
    assert "Draft text." in "\n".join(p.text for p in output.paragraphs)


@pytest.mark.parametrize("mutation", ["template", "disable", "foreign"])
def test_template_mutation_or_revocation_rejected(setup, mutation):
    app, c, h, cfg, pid, _ = setup
    skill = imported(c, h)
    proposal = propose(app, c, h, pid, skill)
    if mutation == "template":
        proposal["spec"]["template"]["asset_sha256"] = "0" * 64
    elif mutation == "disable":
        c.post(
            "/api/skills/" + skill["id"] + "/trust",
            headers=h,
            json={"expected_revision": 1, "sha256": skill["sha256"], "enabled": False},
        )
    else:
        from hub.db import Skill

        with app.state.sessions() as db:
            db.get(Skill, skill["id"]).project_id = c.post(
                "/api/projects", headers=h, json={"name": "Other"}
            ).json()["id"]
            db.commit()
    import uuid

    result = c.post(
        "/api/projects/" + pid + "/artifacts",
        headers=h,
        json={
            "request_id": str(uuid.uuid4()),
            "spec": proposal["spec"],
            "draft_token": proposal["draft_token"],
        },
    )
    assert result.status_code == 409
