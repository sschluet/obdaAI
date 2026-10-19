"""Bounded official Gmail read-only transport; no arbitrary URLs or account IDs.

Mail is untrusted private data. Callers bind credentials and LOCAL_ONLY results to
current integration permissions; this module grants neither agent nor cloud rights.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from email.message import Message
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_RESPONSE_BYTES = 2_000_000
MAX_TEXT_CHARS = 20_000
_ID = re.compile(r"[a-fA-F0-9]{1,64}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_PKCE = re.compile(r"[A-Za-z0-9._~-]{43,128}\Z")


class GmailError(ValueError):
    """A deliberately sanitized transport or validation error."""


def _string(value: Any, limit: int, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or (not value and not empty)
        or len(value) > limit
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise GmailError("Invalid Gmail value")
    return value


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise GmailError("Invalid Gmail message identity")
    return value


def _integer(value: Any, minimum: int = 0, maximum: int = 10**15) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise GmailError("Invalid Gmail numeric value")
    return value


def _redirect(value: str) -> str:
    _string(value, 2048)
    u = urlsplit(value)
    try:
        port = u.port
    except ValueError:
        raise GmailError("Invalid OAuth callback") from None
    if (
        not u.hostname
        or u.username is not None
        or u.password is not None
        or u.query
        or u.fragment
        or not u.path.startswith("/")
        or "\\" in value
        or "%" in value
        or any(p in {".", ".."} for p in u.path.split("/"))
        or (u.scheme != "https" and not (u.scheme == "http" and u.hostname == "127.0.0.1"))
        or port is not None
        and not 1 <= port <= 65535
    ):
        raise GmailError("Invalid OAuth callback")
    return value


def authorization_url(client_id: str, redirect_uri: str, state: str, code_verifier: str) -> str:
    _string(client_id, 1024)
    _string(state, 512)
    if len(state) < 32 or not _PKCE.fullmatch(code_verifier):
        raise GmailError("Invalid OAuth challenge")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
    return (
        AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": _redirect(redirect_uri),
                "response_type": "code",
                "scope": SCOPE,
                "state": state,
                "access_type": "offline",
                "prompt": "consent select_account",
                "include_granted_scopes": "false",
                "code_challenge": challenge.decode().rstrip("="),
                "code_challenge_method": "S256",
            }
        )
    )


def _http_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        verify=True,
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(8, connect=4, pool=2),
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        transport=transport,
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
    )


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    token: str = "",
    params: dict[str, Any] | None = None,
    data: dict[str, str] | None = None,
    empty_ok: bool = False,
    before_send: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    # Internal endpoint selection is still checked immediately before token dispatch.
    if not (
        method == "GET"
        and re.fullmatch(
            re.escape(API_BASE)
            + r"/(?:profile|labels|messages(?:/[a-fA-F0-9]{1,64})?|threads/[a-fA-F0-9]{1,64})",
            url,
        )
        or method == "POST"
        and url in {TOKEN_URL, REVOKE_URL}
    ):
        raise GmailError("Forbidden Gmail operation")
    started = time.monotonic()
    headers = {"Authorization": "Bearer " + _string(token, 8192)} if token else {}
    if before_send:
        before_send()
    try:
        with client.stream(method, url, headers=headers, params=params, data=data) as response:
            if response.status_code != 200:
                raise GmailError("Google request rejected")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise GmailError("Compressed Google response rejected")
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES or time.monotonic() - started > 12:
                    raise GmailError("Google response limit exceeded")
            if empty_ok and not raw:
                return {}
            if response.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise GmailError("Invalid Google response")
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise GmailError("Invalid Google response")
            return body
    except GmailError:
        raise
    except (httpx.HTTPError, ValueError, UnicodeError, RecursionError):
        raise GmailError("Google request failed") from None


def _tokens(body: dict[str, Any], *, refresh: str = "", require_scope: bool) -> dict[str, Any]:
    scope = body.get("scope", None if require_scope else SCOPE)
    if not isinstance(scope, str) or scope.split() != [SCOPE]:
        raise GmailError("Google did not grant exactly read-only Gmail access")
    token_type = body.get("token_type")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise GmailError("Invalid Google token type")
    expires = body.get("expires_in")
    if (
        not isinstance(expires, (int, float))
        or isinstance(expires, bool)
        or not math.isfinite(expires)
        or not 0 < expires <= 86400
    ):
        raise GmailError("Invalid Google token lifetime")
    result = {
        "access_token": _string(body.get("access_token"), 8192),
        "refresh_token": _string(body.get("refresh_token", refresh), 8192, empty=True),
        "expires_at": time.time() + expires,
        "scope": SCOPE,
        "token_type": "Bearer",
    }
    return result


def exchange_code(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
    *,
    transport: httpx.BaseTransport | None = None,
    before_send: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    if not _PKCE.fullmatch(code_verifier):
        raise GmailError("Invalid OAuth challenge")
    data = {
        "grant_type": "authorization_code",
        "client_id": _string(client_id, 1024),
        "client_secret": _string(client_secret, 4096),
        "redirect_uri": _redirect(redirect_uri),
        "code": _string(code, 8192),
        "code_verifier": code_verifier,
    }
    with _http_client(transport) as client:
        return _tokens(
            _request(client, "POST", TOKEN_URL, data=data, before_send=before_send),
            require_scope=True,
        )


def refresh_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    *,
    transport: httpx.BaseTransport | None = None,
    before_send: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    refresh_token = _string(refresh_token, 8192)
    data = {
        "grant_type": "refresh_token",
        "client_id": _string(client_id, 1024),
        "client_secret": _string(client_secret, 4096),
        "refresh_token": refresh_token,
    }
    with _http_client(transport) as client:
        return _tokens(
            _request(client, "POST", TOKEN_URL, data=data, before_send=before_send),
            refresh=refresh_token,
            require_scope=False,
        )


def revoke_token(
    token: str,
    *,
    transport: httpx.BaseTransport | None = None,
    before_send: Callable[[], Any] | None = None,
) -> None:
    with _http_client(transport) as client:
        _request(
            client,
            "POST",
            REVOKE_URL,
            data={"token": _string(token, 8192)},
            empty_ok=True,
            before_send=before_send,
        )


def _bounded_text(value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        raise GmailError("Invalid Gmail text")
    return value[:maximum]


def _message(body: dict[str, Any], max_chars: int) -> dict[str, Any]:
    max_chars = _integer(max_chars, 1, MAX_TEXT_CHARS)
    payload = body.get("payload", {})
    text: list[str] = []
    attachments: list[dict[str, Any]] = []
    remaining, parts, html_omitted, truncated = max_chars, 0, False, False

    def visit(part: Any, depth: int) -> None:
        nonlocal remaining, parts, html_omitted, truncated
        parts += 1
        if not isinstance(part, dict) or depth > 10 or parts > 100:
            raise GmailError("Gmail MIME structure limit exceeded")
        mime = _string(part.get("mimeType", "application/octet-stream"), 128).lower()
        filename = _bounded_text(part.get("filename", ""), 512)
        content = part.get("body", {})
        if not isinstance(content, dict):
            raise GmailError("Invalid Gmail MIME body")
        if filename or content.get("attachmentId"):
            if len(attachments) >= 50:
                truncated = True
            else:
                attachments.append(
                    {
                        "filename": filename,
                        "mimeType": mime,
                        "size": _integer(content.get("size", 0)),
                    }
                )
            return
        elif mime == "text/plain" and content.get("data"):
            encoded = _string(content["data"], MAX_RESPONSE_BYTES)
            if not re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", encoded):
                raise GmailError("Invalid Gmail MIME encoding")
            try:
                raw = base64.b64decode(
                    encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
                )
            except (ValueError, binascii.Error):
                raise GmailError("Invalid Gmail MIME encoding") from None
            charset = "utf-8"
            headers = part.get("headers", [])
            if not isinstance(headers, list) or len(headers) > 100:
                raise GmailError("Invalid Gmail MIME headers")
            for header in headers:
                if (
                    isinstance(header, dict)
                    and str(header.get("name", "")).lower() == "content-type"
                ):
                    value = Message()
                    value["content-type"] = _bounded_text(header.get("value", ""), 2048)
                    charset = value.get_content_charset() or "utf-8"
            try:
                decoded = raw.decode(charset, errors="replace")
            except LookupError:
                decoded = raw.decode("utf-8", errors="replace")
            if len(decoded) > remaining:
                truncated = True
            if remaining:
                text.append(decoded[:remaining])
                remaining -= min(len(decoded), remaining)
        elif mime == "text/html":
            html_omitted = True
        children = part.get("parts", [])
        if not isinstance(children, list) or len(children) > 100:
            raise GmailError("Gmail MIME structure limit exceeded")
        for child in children:
            visit(child, depth + 1)

    visit(payload, 0)
    headers = payload.get("headers", [])
    if not isinstance(headers, list) or len(headers) > 100:
        raise GmailError("Invalid Gmail headers")
    chosen = {}
    for header in headers:
        if isinstance(header, dict):
            key = str(header.get("name", "")).lower()
            if key in {"subject", "from", "to", "cc", "date", "message-id"}:
                chosen[key] = _bounded_text(header.get("value", ""), 2048)
    labels = body.get("labelIds", [])
    if not isinstance(labels, list) or len(labels) > 100:
        raise GmailError("Invalid Gmail labels")
    joined_text = "\n".join(text)
    return {
        "id": _identifier(body.get("id")),
        "threadId": _identifier(body.get("threadId")),
        "headers": chosen,
        "labelIds": [_string(label, 128) for label in labels],
        "snippet": _bounded_text(body.get("snippet", ""), 1000),
        "text": joined_text[:max_chars],
        "attachments": attachments,
        "html_omitted": html_omitted,
        "truncated": truncated or len(joined_text) > max_chars,
        "content_trust": "untrusted_email",
    }


class GmailClient:
    def __init__(
        self,
        access_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        before_send: Callable[[], Any] | None = None,
    ) -> None:
        self._token = _string(access_token, 8192)
        self._client = _http_client(transport)
        self._before_send = before_send

    def __enter__(self) -> GmailClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def profile(self) -> dict[str, Any]:
        body = _request(
            self._client,
            "GET",
            API_BASE + "/profile",
            token=self._token,
            before_send=self._before_send,
        )
        email = _string(body.get("emailAddress"), 254)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+", email):
            raise GmailError("Invalid Gmail account")
        return {
            "emailAddress": email,
            "messagesTotal": _integer(body.get("messagesTotal", 0)),
            "threadsTotal": _integer(body.get("threadsTotal", 0)),
        }

    def labels(self) -> dict[str, Any]:
        body = _request(
            self._client,
            "GET",
            API_BASE + "/labels",
            token=self._token,
            before_send=self._before_send,
        )
        labels = body.get("labels", [])
        if not isinstance(labels, list) or len(labels) > 1000:
            raise GmailError("Gmail label limit exceeded")
        rows = []
        for label in labels:
            if not isinstance(label, dict):
                raise GmailError("Invalid Gmail label")
            name, identity = _string(label.get("name"), 512), _string(label.get("id"), 128)
            if not _LABEL.fullmatch(identity):
                raise GmailError("Invalid Gmail label identity")
            label_type = label.get("type", "user")
            if label_type not in {"user", "system"}:
                raise GmailError("Invalid Gmail label type")
            rows.append({"id": identity, "name": name, "type": label_type})
        return {"labels": rows}

    def messages(
        self,
        query: str = "",
        page_token: str = "",
        limit: int = 20,
        label_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        query, page_token = _string(query, 1024, empty=True), _string(page_token, 2048, empty=True)
        if not isinstance(label_ids, (tuple, list)) or len(label_ids) > 20:
            raise GmailError("Invalid Gmail label selection")
        for label in label_ids:
            if not isinstance(label, str) or not _LABEL.fullmatch(label):
                raise GmailError("Invalid Gmail label identity")
        params: dict[str, Any] = {"maxResults": _integer(limit, 1, 100)}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        if label_ids:
            params["labelIds"] = list(label_ids)
        body = _request(
            self._client,
            "GET",
            API_BASE + "/messages",
            token=self._token,
            params=params,
            before_send=self._before_send,
        )
        rows = body.get("messages", [])
        if not isinstance(rows, list) or len(rows) > limit:
            raise GmailError("Gmail result limit exceeded")
        messages = []
        for row in rows:
            if not isinstance(row, dict):
                raise GmailError("Invalid Gmail message")
            messages.append(
                {"id": _identifier(row.get("id")), "threadId": _identifier(row.get("threadId"))}
            )
        return {
            "messages": messages,
            "nextPageToken": _string(body.get("nextPageToken", ""), 2048, empty=True),
            "resultSizeEstimate": _integer(body.get("resultSizeEstimate", 0)),
        }

    def message(self, message_id: str, max_chars: int = MAX_TEXT_CHARS) -> dict[str, Any]:
        _integer(max_chars, 1, MAX_TEXT_CHARS)
        body = _request(
            self._client,
            "GET",
            API_BASE + "/messages/" + _identifier(message_id),
            token=self._token,
            params={"format": "full"},
            before_send=self._before_send,
        )
        if body.get("id") != message_id:
            raise GmailError("Gmail message identity changed")
        return _message(body, max_chars)

    def thread(self, thread_id: str, max_chars: int = MAX_TEXT_CHARS) -> dict[str, Any]:
        _integer(max_chars, 1, MAX_TEXT_CHARS)
        body = _request(
            self._client,
            "GET",
            API_BASE + "/threads/" + _identifier(thread_id),
            token=self._token,
            params={"format": "full"},
            before_send=self._before_send,
        )
        rows = body.get("messages", [])
        if body.get("id") != thread_id or not isinstance(rows, list) or len(rows) > 100:
            raise GmailError("Gmail thread limit or identity changed")
        messages, remaining = [], max_chars
        for row in rows[:20]:
            if not isinstance(row, dict) or row.get("threadId") != thread_id:
                raise GmailError("Invalid Gmail thread message")
            message = _message(row, max(1, remaining))
            remaining -= len(message["text"])
            if remaining < 0:
                message["text"] = ""
            messages.append(message)
        return {
            "id": thread_id,
            "messages": messages,
            "truncated": len(rows) > 20 or remaining <= 0,
        }
