"""Final source blocks prove current receipts/scope, never certify model prose."""

import json

import pytest
import test_agent_read_references as fixtures
from hub.action_api import digest, encode
from hub.agent_models import AgentStep
from hub.agent_paperless_evidence import paperless_evidence
from hub.agent_tools import Rules


@pytest.fixture(name="archive")
def archive_fixture():
    generator = fixtures.receipt.__wrapped__()
    context = next(generator)
    fixtures.paperless(context)
    yield context
    generator.close()


def read(context, *, seq=1, operation="search", rows=None, query="", page=1, count=None):
    _, job, _, _, original, _, _, _ = context
    document = json.loads(original.document)
    if operation == "search":
        rows = rows if rows is not None else [{"id": 73, "title": "Synthetic receipt", "tags": []}]
        count = len(rows) if count is None else count
        document["arguments"] = {
            "operation": "search",
            "query": query,
            "page": page,
            "limit": 10,
        }
        result = {
            "label": "LOCAL_ONLY",
            "operation": "search",
            "data": {
                "count": count,
                "results": rows,
                "page": page,
                "page_size": 10,
                "has_next": page * 10 < count,
            },
        }
    else:
        document["arguments"] = {"operation": "document", "document_id": 73}
        result = {
            "label": "LOCAL_ONLY",
            "operation": "document",
            "data": {
                "id": 73,
                "title": "Synthetic document",
                "content": "Private OCR is never copied.",
                "tags": [],
                "content_truncated": False,
            },
        }
    return AgentStep(
        job_id=job.id,
        sequence=seq,
        kind="read",
        status="succeeded",
        document=encode(document),
        sha256=digest(encode(document)),
        result=encode(result),
    )


def call(context, history, **kwargs):
    return paperless_evidence(context[1], context[-1], history, **kwargs)


def mutate_document(step, update):
    document = json.loads(step.document)
    update(document)
    step.document = encode(document)
    step.sha256 = digest(step.document)


def mutate_result(step, update):
    result = json.loads(step.result)
    update(result)
    step.result = encode(result)


def test_bounded_search_evidence_contains_actual_rows_and_scope(archive):
    step = read(
        archive,
        rows=[
            {"id": 73, "title": "Observed title", "tags": []},
            {"id": 12, "title": "Second title", "tags": []},
        ],
        count=42,
    )
    text = call(archive, [step])
    assert text.startswith("Quellen und Suchumfang (Paperless)")
    assert "Quelle: Synthetic mailbox" in text
    assert "Seite 1 · Seitengröße 10" in text
    assert "Gesamttreffer laut dieser Suchantwort: 42" in text
    assert "tatsächlich abgerufen: 2 · weitere Seiten: ja" in text
    assert text.index("ID 73") < text.index("ID 12")
    assert "Observed title" in text and "Second title" in text
    assert "Suchtreffer allein belegen keinen gelesenen Dokumentinhalt" in text
    assert "Nicht abgerufene Seiten oder Dokumentinhalte sind dadurch nicht geprüft" in text
    assert len(text.encode()) <= 6000


def test_filtered_empty_is_scoped_not_empty_archive_claim(archive):
    text = call(archive, [read(archive, rows=[], query="invoice AND tag:review")])
    assert "Suchfilter: invoice AND tag\\:review" in text
    assert "Gesamttreffer laut dieser Suchantwort: 0" in text
    assert "Keine Treffer in dieser konkreten Suchantwort" in text
    assert "Archiv ist leer" not in text


def test_pages_and_queries_are_separate_not_deduped_or_added(archive):
    text = call(
        archive, [read(archive, count=42), read(archive, seq=2, page=2, count=42, query="invoice")]
    )
    assert text.count("Gesamttreffer laut dieser Suchantwort: 42") == 2
    assert "Seite 1" in text and "Seite 2" in text
    assert "84" not in text and "werden nicht addiert" in text


@pytest.mark.parametrize("truncated", [False, True, None])
def test_document_id_title_and_actual_ocr_limits_without_content(archive, truncated):
    step = read(archive, operation="document")
    if truncated is None:
        mutate_result(step, lambda r: r["data"].pop("content_truncated"))
    else:
        mutate_result(step, lambda r: r["data"].update(content_truncated=truncated))
    text = call(archive, [step])
    assert "Dokument-ID 73 · Synthetic document" in text
    assert "Private OCR" not in text
    expected = "im Abruf nicht angegeben" if truncated is None else "ja" if truncated else "nein"
    assert "OCR laut Abruf gekürzt: " + expected in text


@pytest.mark.parametrize(
    "change",
    [
        "disabled",
        "rules_disabled",
        "grant",
        "profile_revision",
        "binding_missing",
        "config",
        "passed_config",
        "target",
        "target_revision",
        "target_hash",
        "target_policy",
        "document_hash",
        "operation",
        "document_id",
        "pagination",
        "page",
        "isolation",
        "ocr_flag",
    ],
)
def test_invalid_or_revoked_relevant_receipt_suppresses_whole_block(archive, change):
    _, job, _, _, _, profile, _, profiles = archive
    step = read(
        archive, operation="document" if change in {"document_id", "ocr_flag"} else "search"
    )
    if change == "disabled":
        profile.enabled = False
    elif change == "rules_disabled":
        profiles[profile.id][1].enabled = False
    elif change == "grant":
        profiles[profile.id][1].http_methods = []
    elif change == "profile_revision":
        profile.revision += 1
    elif change == "binding_missing":
        job.bindings = encode({"profiles": []})
    elif change == "config":
        profile.config = encode({"url": "http://changed.invalid"})
    elif change == "passed_config":
        profiles[profile.id][2]["url"] = "http://changed.invalid"
    elif change == "target":
        mutate_document(step, lambda d: d["target"].update(url="http://changed.invalid"))
    elif change == "target_revision":
        mutate_document(step, lambda d: d["target"].update(profile_revision=True))
    elif change == "target_hash":
        mutate_document(step, lambda d: d["target"].update(config_sha256="f" * 64))
    elif change == "target_policy":
        mutate_document(step, lambda d: d["target"].update(policy_revision=999))
    elif change == "document_hash":
        step.document += " "
    elif change == "operation":
        mutate_result(step, lambda r: r.update(operation="document"))
    elif change == "document_id":
        mutate_result(step, lambda r: r["data"].update(id=999))
    elif change == "pagination":
        mutate_result(step, lambda r: r["data"].update(has_next=True))
    elif change == "page":
        mutate_result(step, lambda r: r["data"].update(page=2))
    elif change == "isolation":
        mutate_result(step, lambda r: r.update(label="CLOUD_ALLOWED"))
    else:
        mutate_result(step, lambda r: r["data"].update(content_truncated="false"))
    assert call(archive, [read(archive, seq=2), step]) is None


@pytest.mark.parametrize("status", ["failed", "uncertain", "prepared", "dispatching"])
def test_non_success_suppresses_even_other_successes(archive, status):
    step = read(archive, seq=2)
    step.status = status
    assert call(archive, [read(archive), step]) is None


def test_missing_or_legacy_other_job_receipts_cannot_supply_evidence(archive):
    assert call(archive, []) is None
    other = read(archive)
    other.job_id = "other-job"
    assert call(archive, [other]) is None
    legacy = read(archive)
    mutate_document(legacy, lambda d: d.update(tool="http"))
    assert call(archive, [legacy]) is None


def test_policy_revision_compatibility_and_cancel(archive):
    step = read(archive)
    bound = json.loads(archive[1].bindings)["profiles"][0]
    mutate_document(step, lambda d: d["target"].update(policy_revision=bound["policy_revision"]))
    assert call(archive, [step]) is not None
    archive[1].cancel_requested = True
    assert call(archive, [step]) is None


def test_hostile_names_queries_titles_are_inert_and_clipping_labeled(archive):
    profile = archive[5]
    profile.name = "[click](https://evil.invalid) <script>\u202e" + "x" * 200
    step = read(
        archive,
        query="https://evil.invalid/[secret] " + "a" * 400,
        rows=[{"id": 73, "title": "![x](https://evil.invalid)<img> " + "t" * 400, "tags": []}],
    )
    text = call(archive, [step])
    assert "https://" not in text and "<script>" not in text and "<img>" not in text
    assert "![" not in text and "](" not in text and "\u202e" not in text
    assert text.count("(gekürzt)") >= 3
    assert "ID 73" in text


def test_output_budget_keeps_ids_or_labels_omitted_receipts(archive):
    rows = [{"id": n, "title": "ü" * 400, "tags": []} for n in range(1, 11)]
    history = [read(archive, seq=n, rows=rows) for n in range(1, 12)]
    text = call(archive, history, max_bytes=1200)
    assert text is not None and len(text.encode()) <= 1200
    assert "Titel ausgelassen (Ausgabegrenze)" in text
    assert all("ID " + str(n) in text for n in range(1, 11))
    assert "weitere gültige Abrufbelege ausgelassen" in text
    history[-1].status = "failed"
    assert call(archive, history, max_bytes=1200) is None


@pytest.mark.parametrize("limit", [0, True, 1023, 10001])
def test_bad_output_budgets_rejected(archive, limit):
    with pytest.raises(ValueError):
        call(archive, [read(archive)], max_bytes=limit)


def test_multiple_accounts_remain_separate_even_with_same_document_id(archive):
    from hub.integrations import Integration

    db, job, _, _, _, _, _, profiles = archive
    profile = Integration(
        kind="paperless",
        name="Second archive",
        enabled=True,
        config=encode({"url": "http://second.invalid/api"}),
    )
    db.add(profile)
    db.flush()
    rules = Rules(enabled=True, http_methods=["GET"], http_prefixes=["/api/documents/"])
    profiles[profile.id] = (profile, rules, {**json.loads(profile.config), "kind": "paperless"})
    binding = json.loads(job.bindings)
    binding["profiles"].append(
        {
            "id": profile.id,
            "profile_revision": profile.revision,
            "policy_revision": 9,
        }
    )
    job.bindings = encode(binding)
    step = read(archive, seq=2, count=3)
    mutate_document(step, lambda d: d.update(integration_id=profile.id))
    mutate_document(
        step,
        lambda d: d["target"].update(
            url="http://second.invalid/api",
            profile_revision=profile.revision,
            config_sha256=digest(profile.config),
            policy_revision=9,
        ),
    )
    text = call(archive, [read(archive, count=42), step])
    assert "Quelle: Synthetic mailbox" in text and "Quelle: Second archive" in text
    assert text.count("ID 73") == 2
    assert "Suchantwort: 42" in text and "Suchantwort: 3" in text
    assert "Suchantwort: 45" not in text


@pytest.mark.parametrize("change", ["result_json", "document_json", "arguments", "duplicate"])
def test_malformed_or_duplicate_relevant_evidence_fails_closed(archive, change):
    step = read(archive)
    history = [step]
    if change == "result_json":
        step.result = "not-json"
    elif change == "document_json":
        step.document = "not-json"
    elif change == "arguments":
        mutate_document(step, lambda d: d["arguments"].update(operation="download"))
    else:
        history.append(read(archive))
    assert call(archive, history) is None


def test_formatter_does_not_call_network_or_provider(archive, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Final evidence formatting must perform no network or provider calls")

    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("hub.agent_paperless.invoke", forbidden)
    text = call(archive, [read(archive)])
    assert text is not None and "ID 73" in text
