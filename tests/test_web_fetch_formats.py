"""Public documentation remains inert, bounded and pinned for every text format."""

import asyncio

import httpx
import pytest
from hub.config import Settings
from hub.websearch import fetch_page


def public_response(monkeypatch, media_type, text, status=200):
    real_client = httpx.AsyncClient
    calls = []
    monkeypatch.setattr(
        "hub.websearch.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.215.14", 443))],
    )

    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"Content-Type": media_type}, text=text)

    monkeypatch.setattr(
        "hub.websearch.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    return calls


@pytest.mark.parametrize(
    ("media_type", "source", "expected"),
    [
        ("text/html; charset=utf-8", "<h1>API</h1><script>ignored()</script>", "API"),
        (
            "text/plain; charset=utf-8",
            "# API\nPOST /api/example/\n<b>literal</b>",
            "# API\nPOST /api/example/\n<b>literal</b>",
        ),
        (
            "Application/JSON; charset=utf-8",
            '{"paths":{"/api/example/":{}}}',
            '{"paths":{"/api/example/":{}}}',
        ),
    ],
)
def test_public_documentation_formats_preserve_text_and_pinned_identity(
    monkeypatch, media_type, source, expected
):
    calls = public_response(monkeypatch, media_type, source)
    result = asyncio.run(
        fetch_page(Settings(), "https://example.org/api/spec", True, user_selected=True)
    )
    assert result == expected
    assert len(calls) == 1
    assert str(calls[0].url) == "https://93.184.215.14/api/spec"
    assert calls[0].headers["host"] == "example.org"
    assert calls[0].extensions["sni_hostname"] == "example.org"


@pytest.mark.parametrize("media_type", ["text/plain", "application/json"])
@pytest.mark.parametrize("size", [21000, 1_000_001])
def test_public_text_formats_keep_download_and_visible_text_limits(monkeypatch, media_type, size):
    public_response(monkeypatch, media_type, "x" * size)
    if size > 1_000_000:
        with pytest.raises(ValueError, match="groß"):
            asyncio.run(
                fetch_page(Settings(), "https://example.org/spec", True, user_selected=True)
            )
    else:
        result = asyncio.run(
            fetch_page(Settings(), "https://example.org/spec", True, user_selected=True)
        )
        assert len(result) == 20000


@pytest.mark.parametrize(
    "media_type",
    ["application/zip", "application/octet-stream", "application/javascript", "image/png", ""],
)
def test_other_formats_remain_rejected(monkeypatch, media_type):
    public_response(monkeypatch, media_type, "untrusted")
    with pytest.raises(ValueError, match="Quellen"):
        asyncio.run(fetch_page(Settings(), "https://example.org/spec", True, user_selected=True))


def test_public_text_does_not_follow_redirects(monkeypatch):
    calls = public_response(monkeypatch, "text/plain", "redirect", status=302)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fetch_page(Settings(), "https://example.org/spec", True, user_selected=True))
    assert len(calls) == 1
