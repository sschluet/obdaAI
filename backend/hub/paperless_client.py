"""Bounded read-only Paperless-ngx API using a pinned configured endpoint."""

import json
import re
import time
from typing import Any

import httpx

from hub.config import Settings
from hub.integration_transport import canonical_url, pinned_target

MAX_JSON_BYTES = 2_000_000
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_CONTENT_CHARS = 100_000


class PaperlessClient:
    def __init__(self, client: httpx.Client, cfg: Settings, url: str, token: str):
        if not token or len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("Invalid Paperless credential")
        base = canonical_url(url).rstrip("/")
        # A profile may point at the application root or its API root.
        if base.endswith("/api"):
            base = base[:-4]
        self.base, self.headers, self.extensions = pinned_target(cfg, base)
        self.headers.update(
            {
                "Authorization": "Token " + token,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            }
        )
        self.client = client
        self.deadline = time.monotonic() + 25

    def get(
        self, path: str, params: dict[str, Any] | None = None, *, binary: bool = False
    ) -> tuple[bytes, str]:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Paperless request deadline")
        with self.client.stream(
            "GET",
            self.base.rstrip("/") + path,
            params=params,
            headers=self.headers,
            extensions=self.extensions,
            follow_redirects=False,
            timeout=min(10, remaining),
        ) as response:
            if response.status_code != 200:
                raise ValueError("Paperless access or HTTP failure")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("Compressed Paperless responses unsupported")
            mime = response.headers.get("content-type", "").split(";")[0].strip()
            if not binary and mime != "application/json":
                raise ValueError("Invalid Paperless response type")
            data = bytearray()
            maximum = MAX_DOWNLOAD_BYTES if binary else MAX_JSON_BYTES
            for chunk in response.iter_bytes(chunk_size=65536):
                data.extend(chunk)
                if len(data) > maximum or time.monotonic() > self.deadline:
                    raise ValueError("Paperless response exceeds limit")
            return bytes(data), mime

    def json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return json.loads(self.get(path, params)[0])


def metadata(value: Any, *, include_content: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or type(value.get("id")) is not int or value["id"] < 1:
        raise ValueError("Invalid Paperless document")
    result: dict[str, Any] = {"id": value["id"]}
    for key in ("title", "created", "added", "modified", "original_file_name"):
        text = value.get(key)
        if text is not None and (
            not isinstance(text, str) or len(text) > 1024 or any(ord(c) < 32 for c in text)
        ):
            raise ValueError("Invalid Paperless metadata")
        result[key] = text or ""
    for key in ("correspondent", "document_type"):
        identifier = value.get(key)
        if identifier is not None and (type(identifier) is not int or identifier < 1):
            raise ValueError("Invalid Paperless metadata ID")
        result[key] = identifier
    tags = value.get("tags", [])
    if (
        not isinstance(tags, list)
        or len(tags) > 512
        or any(type(tag) is not int or tag < 1 for tag in tags)
    ):
        raise ValueError("Invalid Paperless tags")
    result["tags"] = tags
    if include_content:
        content = value.get("content", "")
        if not isinstance(content, str):
            raise ValueError("Invalid Paperless OCR content")
        result["content"] = content[:MAX_CONTENT_CHARS]
        result["content_truncated"] = len(content) > MAX_CONTENT_CHARS
    return result


def list_documents(
    client: httpx.Client,
    cfg: Settings,
    url: str,
    token: str,
    *,
    query: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    if (
        len(query) > 500
        or any(ord(c) < 32 for c in query)
        or not 1 <= page <= 10000
        or not 1 <= page_size <= 50
    ):
        raise ValueError("Invalid Paperless search")
    params: dict[str, Any] = {
        "page": page,
        "page_size": page_size,
        "ordering": "-created",
        "fields": (
            "id,title,created,added,modified,correspondent,document_type,tags,original_file_name"
        ),
    }
    if query.strip():
        params["query"] = query.strip()
    value = PaperlessClient(client, cfg, url, token).json("/api/documents/", params)
    if (
        not isinstance(value, dict)
        or type(value.get("count")) is not int
        or value["count"] < 0
        or not isinstance(value.get("results"), list)
        or len(value["results"]) > page_size
    ):
        raise ValueError("Invalid Paperless list")
    return {
        "label": "LOCAL_ONLY",
        "count": value["count"],
        "page": page,
        "page_size": page_size,
        "has_next": page * page_size < value["count"],
        "results": [metadata(item) for item in value["results"]],
    }


def document(
    client: httpx.Client, cfg: Settings, url: str, token: str, document_id: int
) -> dict[str, Any]:
    if document_id < 1:
        raise ValueError("Invalid document ID")
    result = metadata(
        PaperlessClient(client, cfg, url, token).json(f"/api/documents/{document_id}/"),
        include_content=True,
    )
    if result["id"] != document_id:
        raise ValueError("Paperless document mismatch")
    return {"label": "LOCAL_ONLY", **result}


def download(
    client: httpx.Client, cfg: Settings, url: str, token: str, document_id: int
) -> tuple[bytes, str]:
    if document_id < 1:
        raise ValueError("Invalid document ID")
    data, mime = PaperlessClient(client, cfg, url, token).get(
        f"/api/documents/{document_id}/download/", {"original": "true"}, binary=True
    )
    if not data or not re.fullmatch(r"[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+", mime):
        raise ValueError("Invalid original document")
    return data, mime


def assessment(client: httpx.Client, cfg: Settings, url: str, token: str) -> dict[str, Any]:
    result = list_documents(client, cfg, url, token, page_size=1)
    return {
        "label": "LOCAL_ONLY",
        "document_count": result["count"],
        "scope": "document_search_ocr_original_read",
        "writes_enabled": False,
    }
