import json

import httpx
import pytest
from hub.n8n_check import MAX_RESPONSE, ORIGIN, CheckError, ConnectionCheck
from hub.n8n_drafts import connection_draft

TASK = "00000000-0000-4000-8000-000000000001"
REVIEW = {"task_id": TASK, "revision": 1, "spec_sha256": "a" * 64}
REVIEW["payload"] = connection_draft(TASK, 1, "a" * 64)


def remote(**changes):
    return {**REVIEW["payload"], "id": "synthetic123", "active": False, **changes}


def fixture(handler):
    return ConnectionCheck(httpx.Client(transport=httpx.MockTransport(handler)), "synthetic-key")


def test_create_verify_and_second_invocation_no_second_post(tmp_path):
    seen = []
    created = False

    def handler(request):
        nonlocal created
        seen.append(request)
        assert str(request.url).startswith(ORIGIN + "/api/v1/")
        assert request.headers["X-N8N-API-KEY"] == "synthetic-key"
        if request.method == "POST":
            assert json.loads(request.content) == REVIEW["payload"]
            created = True
            return httpx.Response(200, json=remote())
        if request.url.path.endswith("/synthetic123"):
            assert created
            return httpx.Response(200, json=remote())
        return httpx.Response(200, json={"data": [], "nextCursor": None})

    adapter = fixture(handler)
    journal = tmp_path / "receipt.json"
    receipt = adapter.ensure(REVIEW, journal, approved=True)
    assert receipt["inactive"] and not receipt["executes_task"]
    adapter.ensure(REVIEW, journal)
    assert sum(r.method == "POST" for r in seen) == 1
    assert journal.stat().st_mode & 0o077 == 0


def test_unapproved_no_mutation(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.method)
        return httpx.Response(200, json={"data": []})

    with pytest.raises(CheckError, match="approval"):
        fixture(handler).ensure(REVIEW, tmp_path / "receipt.json")
    assert seen == ["GET"]


def test_unknown_create_outcome_reconciles_without_repeated_post(tmp_path):
    posted = 0

    def handler(request):
        nonlocal posted
        if request.method == "POST":
            posted += 1
            raise httpx.ReadTimeout("synthetic secret error", request=request)
        return httpx.Response(200, json={"data": []})

    adapter = fixture(handler)
    journal = tmp_path / "receipt.json"
    with pytest.raises(CheckError, match="reconcile"):
        adapter.ensure(REVIEW, journal, approved=True)
    with pytest.raises(CheckError, match="uncertain"):
        adapter.ensure(REVIEW, journal, approved=True)
    assert posted == 1


def test_unknown_outcome_matching_workflow_is_recovered(tmp_path):
    posted = 0

    def handler(request):
        nonlocal posted
        if request.method == "POST":
            posted += 1
            raise httpx.ReadTimeout("after successful creation", request=request)
        if request.url.path.endswith("/synthetic123"):
            return httpx.Response(200, json=remote())
        return httpx.Response(200, json={"data": [remote()] if posted else []})

    adapter = fixture(handler)
    journal = tmp_path / "receipt.json"
    with pytest.raises(CheckError):
        adapter.ensure(REVIEW, journal, approved=True)
    assert adapter.ensure(REVIEW, journal)["status"] == "verified"
    assert posted == 1


@pytest.mark.parametrize(
    "changed",
    [
        {"active": True},
        {"nodes": []},
        {"settings": {}},
        {"pinData": {"private": "synthetic"}},
        {"activeVersionId": "published"},
        {"id": "../../credentials"},
    ],
)
def test_drift_stops_without_overwriting_existing_workflow(tmp_path, changed):
    seen = []

    def handler(request):
        seen.append(request.method)
        return httpx.Response(200, json={"data": [remote(**changed)]})

    with pytest.raises(CheckError):
        fixture(handler).ensure(REVIEW, tmp_path / "receipt.json", approved=True)
    assert seen == ["GET"]


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_auth_redirect_or_server_failure_no_retry_or_secret_output(tmp_path, status):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, headers={"Location": "https://evil.example"}, text="secret")

    with pytest.raises(CheckError) as result:
        fixture(handler).ensure(REVIEW, tmp_path / "receipt.json", approved=True)
    assert "secret" not in str(result.value) and len(seen) == 1


def test_duplicate_identity_and_oversize_response_fail_closed(tmp_path):
    for response in (
        httpx.Response(200, json={"data": [remote(), remote()]}),
        httpx.Response(200, content=b" " * (MAX_RESPONSE + 1)),
    ):
        with pytest.raises(CheckError):
            fixture(lambda request, response=response: response).ensure(
                REVIEW, tmp_path / "receipt.json", approved=True
            )


def test_concurrent_operator_attempt_cannot_create_a_second_workflow(tmp_path):
    import concurrent.futures
    import threading

    entered, release = threading.Event(), threading.Event()
    journal = tmp_path / "receipt.json"
    posts = []

    def handler(request):
        if request.method == "POST":
            posts.append(request)
            entered.set()
            assert release.wait(3)
            return httpx.Response(200, json=remote())
        if request.url.path.endswith("/synthetic123"):
            return httpx.Response(200, json=remote())
        return httpx.Response(200, json={"data": []})

    adapter = fixture(handler)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        first = pool.submit(adapter.ensure, REVIEW, journal, approved=True)
        try:
            assert entered.wait(3)
            with pytest.raises(CheckError, match="active"):
                adapter.ensure(REVIEW, journal, approved=True)
        finally:
            release.set()
        assert first.result()["status"] == "verified"
    assert len(posts) == 1
