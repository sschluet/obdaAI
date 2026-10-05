import base64
import hashlib
import json
import uuid

import httpx
import pytest
from fastapi import HTTPException
from hub.browser_read import approved, fetch, snapshot
from hub.config import Settings
from test_actions import execute, gateway  # noqa: F401

ROW = {"name": "Synthetic public page", "url": "https://example.org/help", "ip": "93.184.215.14"}
SHA = hashlib.sha256(json.dumps(ROW, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nsynthetic-only").decode()


def cfg(tmp_path):
    request = tmp_path / "requests"
    result = tmp_path / "results"
    request.mkdir()
    result.mkdir()
    return Settings(
        browser_targets_json=json.dumps({"example": ROW}),
        browser_request_dir=str(request),
        browser_result_dir=str(result),
    )


@pytest.mark.parametrize(
    "row",
    [
        dict(ROW, url="http://example.org/"),
        dict(ROW, ip="127.0.0.1"),
        dict(ROW, ip="192.168.117.100"),
        dict(ROW, ip="169.254.169.254"),
        dict(ROW, url="https://example.org/?token=private"),
        dict(ROW, url="https://user:secret@example.org/"),
        dict(ROW, url="https://example.org:8006/"),
    ],
)
def test_unsafe_targets_block_before_io(tmp_path, row):
    settings = cfg(tmp_path)
    object.__setattr__(settings, "browser_targets_json", json.dumps({"x": row}))
    sha = hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(HTTPException):
        approved(settings, "x", sha)


def test_pinned_fetch_and_no_cookies():
    def handler(r):
        assert str(r.url) == "https://93.184.215.14/help" and r.headers["Host"] == "example.org"
        assert "Cookie" not in r.headers and "Authorization" not in r.headers
        return httpx.Response(200, headers={"Content-Type": "text/html"}, text="<h1>Public</h1>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert fetch(c, ROW) == "<h1>Public</h1>"


@pytest.mark.parametrize(
    "status,headers,body",
    [
        (302, {"Location": "https://169.254.169.254/"}, ""),
        (200, {"Content-Type": "application/pdf"}, ""),
        (200, {"Content-Type": "text/html", "Content-Encoding": "gzip"}, ""),
        (200, {"Content-Type": "text/html"}, "x" * 1_000_001),
    ],
)
def test_redirect_format_compression_and_size_limits(status, headers, body):
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(status, headers=headers, content=body.encode())
            )
        ) as c,
        pytest.raises(ValueError),
    ):
        fetch(c, ROW)


def test_spool_restart_resumes_original_not_network(tmp_path):
    settings = cfg(tmp_path)
    identifier = str(uuid.uuid4())
    html = "<p>Original</p>"
    sha = hashlib.sha256(html.encode()).hexdigest()
    (tmp_path / "requests" / (identifier + ".json")).write_text(
        json.dumps({"id": identifier, "html": html, "sha256": sha})
    )
    result = tmp_path / "results" / (identifier + ".json")
    result.write_text(
        json.dumps(
            {
                "id": identifier,
                "sha256": sha,
                "text": "Original",
                "png": PNG,
                "network": False,
                "javascript": False,
            }
        )
    )
    data = snapshot(settings, identifier, {"target_id": "example", "target_sha256": SHA})
    assert (
        data["html_sha256"] == sha
        and not data["automatic_model_context"]
        and not data["live_interaction"]
    )
    result.write_text(result.read_text().replace('"network": false', '"network": true'))
    with pytest.raises(HTTPException):
        snapshot(settings, identifier, {"target_id": "example", "target_sha256": SHA})


def test_action_drift_replay_and_authenticated_preview(gateway, tmp_path, monkeypatch):  # noqa: F811
    app, c, h, settings = gateway
    config = cfg(tmp_path)
    for field in ("browser_targets_json", "browser_request_dir", "browser_result_dir"):
        object.__setattr__(settings, field, getattr(config, field))
    calls = []

    def render(cfg, aid, params):
        approved(cfg, params["target_id"], params["target_sha256"])
        calls.append(aid)
        return {"name": "Synthetic page", "text": "Visible text", "png": PNG, "label": "LOCAL_ONLY"}

    monkeypatch.setattr("hub.browser_read.snapshot", render)

    def propose():
        r = c.post(
            "/api/actions",
            headers=h,
            json={
                "request_id": str(uuid.uuid4()),
                "tool_id": "browser.inspect",
                "parameters": {"target_id": "example", "target_sha256": SHA},
            },
        )
        assert r.status_code == 200, r.text
        return r.json()

    a = propose()
    result = execute(c, h, a)
    assert result.status_code == 200 and "png" not in result.json()["receipt"]
    assert execute(c, h, a).json() == result.json() and len(calls) == 1
    preview = result.json()["receipt"]["preview_url"]
    assert c.get(preview).content.startswith(b"\x89PNG")
    c.cookies.clear()
    assert c.get(preview).status_code == 401
    login = c.post(
        "/api/login",
        headers={"Origin": settings.origin},
        json={"password": "synthetic-action-password"},
    )
    h["X-CSRF-Token"] = login.json()["csrf"]
    pending = propose()
    object.__setattr__(settings, "browser_targets_json", "{}")
    assert execute(c, h, pending).status_code == 403 and len(calls) == 1
