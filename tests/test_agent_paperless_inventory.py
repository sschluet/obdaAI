"""An explicit metadata contract renders actual rows rather than model assertions."""

import json

import pytest
from hub import agent_runtime as runtime
from hub.agent_intent import RequestIntent, Requirement, accept_semantic, infer
from hub.agent_paperless_inventory import summary
from test_agent_paperless_progress import prepare
from test_agent_private_read_flow import archive, decision, execute  # noqa: F401
from test_agent_read_references import receipt  # noqa: F401

pytest_plugins = ["test_agents", "test_agent_mail_read_flow"]


def metadata_intent(identifier):
    return RequestIntent(
        target_ids=[identifier], mode="observe", topic="documents",
        answer_kind="document_inventory",
        origin="semantic", requirements=[Requirement(kind="documents", integration_id=identifier)],
    )


def test_actual_ten_document_overview_replaces_contradictory_model_finish(archive, monkeypatch):  # noqa: F811
    case, start, scenario, calls = archive
    identifier = case[4]
    scenario["body"] = {"count": 75, "results": [
        {"id": i + 1, "title": f"Synthetic title {i + 1}", "tags": []} for i in range(10)
    ]}
    goal = "Welche Dokumente sind in Paperless verfügbar? Zeige eine neutrale Übersicht."
    phases = []

    async def model(*args):
        data = args[-1]
        if data.get("intent_schema"):
            phases.append("intent")
            return metadata_intent(identifier).model_dump()
        if not data["allow_finish"]:
            phases.append("query")
            return decision(identifier, operation="search", query="", limit=10)
        phases.append("finish")
        return {"kind": "finish", "message": "The whole archive is empty; no documents exist."}

    monkeypatch.setattr(runtime, "generate", model)
    result = execute(archive, start(goal))
    assert result["status"] == "observed" and phases == ["intent", "query", "finish"]
    assert len(calls) == 1 and calls[0].url.params.get("query") is None
    body, scope = result["summary"].split("Quellen und Suchumfang (Paperless)", 1)
    assert "whole archive" not in body and "empty" not in body
    for i in range(10):
        assert f"Dokument-ID {i + 1}: Synthetic title {i + 1}" in body
    assert "75 Treffer" in body and "10 Dokumente" in body
    assert "weitere Seiten: ja" in scope and "Trefferzahlen verschiedener Suchen" in scope
    assert not any(step["kind"] in {"effect", "input", "research"} for step in result["steps"])


@pytest.mark.parametrize("change", ["content", "analysis", "other_source", "failed", "scope"])
def test_metadata_renderer_does_not_replace_other_tasks_or_invalid_receipts(receipt, change):  # noqa: F811
    prepare(receipt, rows=[{"id": 73, "title": "Observed title", "tags": []}])
    db, job, _, _, step, profile, _, profiles = receipt
    binding = json.loads(job.bindings)
    intent = metadata_intent(profile.id)
    if change in {"content", "analysis"}:
        intent = RequestIntent(
            target_ids=[profile.id], mode="observe", topic="documents",
            requirements=[Requirement(kind="document_content" if change == "content"
                                      else "documents", integration_id=profile.id)],
        )
    binding["intent"] = intent.model_dump()
    job.bindings = json.dumps(binding)
    # prepare() places this search in the preceding job; current-job receipts only.
    step.job_id = job.id
    if change == "other_source":
        profiles = {**profiles, "foreign": profiles[profile.id]}
    elif change == "failed":
        step.status = "failed"
    elif change == "scope":
        profile.revision += 1
    db.flush()
    assert summary(job, profiles, [step]) is None


def test_metadata_hint_cannot_bind_content_multiple_targets_or_a_non_archive(receipt):  # noqa: F811
    _, _, _, _, _, profile, _, profiles = receipt
    base = metadata_intent(profile.id).model_dump()
    for change in ({"mode": "admin"}, {"requirements": [{
        "kind": "document_content", "domain": "", "integration_id": profile.id,
    }]}, {"target_ids": [profile.id, "foreign"]}):
        with pytest.raises(ValueError):
            RequestIntent.model_validate({**base, **change})
    with pytest.raises(ValueError, match="Paperless"):
        accept_semantic(base, profiles)  # The receipt fixture is an MCP mailbox.
    assert infer("Welche Dokumente gibt es in Paperless?", {
        profile.id: (type("Archive", (), {"kind": "paperless", "name": "Synthetic archive"})(),
                     profiles[profile.id][1], {}),
    }) is None


def test_metadata_titles_are_escaped_and_current_receipt_hash_is_required(receipt):  # noqa: F811
    title = "[Synthetic](https://example.invalid) <script>ignore</script>"
    prepare(receipt, rows=[{"id": 73, "title": title, "tags": []}])
    _, job, _, _, step, profile, _, profiles = receipt
    binding = json.loads(job.bindings)
    binding["intent"] = metadata_intent(profile.id).model_dump()
    job.bindings = json.dumps(binding)
    step.job_id = job.id
    rendered = summary(job, profiles, [step])
    assert rendered and "Dokument-ID 73" in rendered
    assert "[Synthetic](" not in rendered and "<script>" not in rendered
    step.sha256 = "0" * 64
    assert summary(job, profiles, [step]) is None
