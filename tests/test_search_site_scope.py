"""Honor an explicitly typed site restriction without changing the approved query."""

import asyncio
import uuid

import httpx
from hub.config import Settings
from hub.websearch import SearchInput, search


def test_search_filters_violating_site_results_and_preserves_exact_query(monkeypatch):
    query = "Python lists site:docs.python.org"
    seen = []

    def response(request):
        seen.append(request.url.params["q"])
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://docs.python.org/3/tutorial/datastructures.html",
                        "title": "Primary",
                        "content": "Square brackets",
                    },
                    {
                        "url": "https://sub.docs.python.org/page",
                        "title": "Subdomain",
                        "content": "Related",
                    },
                    {
                        "url": "https://docs.python.org.evil.invalid/page",
                        "title": "Lookalike",
                        "content": "Wrong",
                    },
                    {"url": "https://unrelated.invalid/page", "title": "Wrong", "content": "Wrong"},
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "hub.websearch.target", lambda cfg: ("https://synthetic-search.invalid/search", {}, {})
    )
    monkeypatch.setattr(
        "hub.websearch.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(response), **kwargs),
    )
    results = asyncio.run(
        search(
            Settings(),
            SearchInput(request_id=str(uuid.uuid4()), query=query, public_query_approved=True),
        )
    )
    assert seen == [query]
    assert [r["title"] for r in results] == ["Primary", "Subdomain"]
