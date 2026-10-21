import asyncio
import json

import httpx
import pytest
from hub.config import Settings
from hub.memory_embeddings import checked_vector, embed, similarity


def config(**changes):
    return Settings(
        **{
            "local_endpoints_json": '{"http://127.0.0.1:9123/v1":"127.0.0.1"}',
            "memory_embedding_base_url": "http://127.0.0.1:9123/v1",
            "memory_embedding_model": "synthetic-embedding-v1",
            **changes,
        }
    )


@pytest.mark.parametrize(
    "value", [[], [0, 0], [True], [float("nan")], [float("inf")], [1e20], "vector", [1] * 3073]
)
def test_embedding_shape_bounded_and_finite(value):
    with pytest.raises(ValueError):
        checked_vector(value)


def test_dimension_mismatch_not_semantic_match():
    assert similarity([1, 0], [1]) == 0


def test_local_embeddings_real_http_contract_bounded_transport(monkeypatch):
    original = httpx.AsyncClient
    seen = []

    def respond(request):
        seen.append(request)
        assert str(request.url) == "http://127.0.0.1:9123/v1/embeddings"
        assert json.loads(request.content) == {
            "input": "synthetic local fact",
            "model": "synthetic-embedding-v1",
            "encoding_format": "float",
        }
        return httpx.Response(
            200,
            json={
                "model": "synthetic-embedding-v1",
                "data": [{"index": 0, "embedding": [0.25, 0.5]}],
            },
        )

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr("hub.memory_embeddings.httpx.AsyncClient", client)
    assert asyncio.run(embed(config(), "synthetic local fact")) == [0.25, 0.5]
    assert len(seen) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"memory_embedding_base_url": "https://api.openai.com/v1"},
        {"local_allowed_labels": ("CLOUD_ALLOWED",)},
        {"local_endpoints_json": "{}"},
        {"memory_embedding_model": ""},
    ],
)
def test_unapproved_or_unconfigured_embedding_no_network(monkeypatch, changes):
    def denied(**kwargs):
        pytest.fail("Unapproved embedding attempted HTTP")

    monkeypatch.setattr("hub.memory_embeddings.httpx.AsyncClient", denied)
    assert asyncio.run(embed(config(**changes), "synthetic local fact")) is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://example.org"}),
        httpx.Response(500),
        httpx.Response(200, content=b'{"data":[{"embedding":[NaN]}]}'),
        httpx.Response(200, json={"model": "different", "data": [{"embedding": [1]}]}),
        httpx.Response(200, content=b"x" * 200001),
    ],
)
def test_bad_embedding_response_degrades_without_fallback(monkeypatch, response):
    original = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(request)
        return response

    monkeypatch.setattr(
        "hub.memory_embeddings.httpx.AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)),
    )
    assert asyncio.run(embed(config(), "synthetic local fact")) is None
    assert len(calls) == 1
