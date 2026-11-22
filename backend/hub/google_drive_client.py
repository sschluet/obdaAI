"""Bounded official Google Drive transport; credentials never reach arbitrary URLs."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import secrets
import time
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import httpx

READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"
EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}
MAX_BYTES = 25 * 1024 * 1024
MAX_JSON = 2_000_000
FIELDS = (
    "id,name,mimeType,size,modifiedTime,parents,appProperties,md5Checksum,trashed,"
    "ownedByMe,capabilities(canAddChildren)"
)
_ID = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
_PKCE = re.compile(r"[A-Za-z0-9._~-]{43,128}\Z")


class DriveError(ValueError):
    """Sanitized protocol failure, never Google response text or tokens."""


def string(value: Any, limit: int = 1024, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or (not value and not empty)
        or len(value) > limit
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise DriveError("Invalid Google Drive value")
    return value


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise DriveError("Invalid Google Drive identity")
    return value


def scopes(source: bool, storage: bool) -> list[str]:
    return ([READ_SCOPE] if source else []) + ([WRITE_SCOPE] if storage else [])


def checked_scopes(value: Any) -> list[str]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or not all(isinstance(x, str) for x in value)
        or len(value) != len(set(value))
    ):
        raise DriveError("Google Drive capabilities required")
    if any(x not in {READ_SCOPE, WRITE_SCOPE} for x in value):
        raise DriveError("Invalid Google Drive scope")
    return sorted(value)


def redirect(value: str) -> str:
    string(value, 2048)
    u = urlsplit(value)
    if (
        not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
        or not u.path.startswith("/")
        or "\\" in value
        or "%" in value
        or any(p in {".", ".."} for p in u.path.split("/"))
        or (u.scheme != "https" and not (u.scheme == "http" and u.hostname == "127.0.0.1"))
    ):
        raise DriveError("Invalid OAuth callback")
    return value


def authorization_url(
    client_id: str, redirect_uri: str, state: str, code_verifier: str, requested_scopes: list[str]
) -> str:
    if len(string(state, 512)) < 32 or not _PKCE.fullmatch(code_verifier):
        raise DriveError("Invalid OAuth challenge")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
    return (
        AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": string(client_id),
                "redirect_uri": redirect(redirect_uri),
                "response_type": "code",
                "scope": " ".join(checked_scopes(requested_scopes)),
                "state": state,
                "access_type": "offline",
                "prompt": "consent select_account",
                "include_granted_scopes": "false",
                "code_challenge": challenge.rstrip(b"=").decode(),
                "code_challenge_method": "S256",
            }
        )
    )


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(12, connect=4),
        transport=transport,
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
    )


def _allowed(method: str, url: str) -> bool:
    return bool(
        method == "POST"
        and url in {TOKEN_URL, REVOKE_URL, API_BASE + "/files", UPLOAD_URL}
        or method == "GET"
        and re.fullmatch(
            re.escape(API_BASE)
            + r"/(?:about|files(?:/generateIds|/[A-Za-z0-9_-]{1,200}(?:/export)?)?)",
            url,
        )
    )


def request(
    c: httpx.Client,
    method: str,
    url: str,
    *,
    token: str = "",
    before_send: Callable[[], Any] | None = None,
    binary: bool = False,
    content: bytes | None = None,
    content_type: str | None = None,
    params: dict[str, Any] | None = None,
    data: dict[str, str] | None = None,
    document: dict[str, Any] | None = None,
    empty_ok: bool = False,
) -> Any:
    if not _allowed(method, url):
        raise DriveError("Forbidden Google Drive operation")
    headers = {"Authorization": "Bearer " + string(token, 8192)} if token else {}
    if content_type:
        headers["Content-Type"] = content_type
    if before_send:
        before_send()
    started = time.monotonic()
    try:
        with c.stream(
            method, url, params=params, data=data, json=document, content=content, headers=headers
        ) as response:
            if response.status_code not in (200, 201):
                raise DriveError("Google Drive request rejected")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise DriveError("Compressed Google Drive response rejected")
            raw = bytearray()
            for block in response.iter_bytes():
                raw.extend(block)
                if (
                    len(raw) > (MAX_BYTES if binary else MAX_JSON)
                    or time.monotonic() - started > 30
                ):
                    raise DriveError("Google Drive response limit exceeded")
            if before_send:
                before_send()
            if binary:
                return bytes(raw)
            if empty_ok and not raw:
                return {}
            if response.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise DriveError("Invalid Google Drive response")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise DriveError("Invalid Google Drive response")
            return value
    except DriveError:
        raise
    except (httpx.HTTPError, ValueError, UnicodeError, RecursionError):
        raise DriveError("Google Drive request failed") from None


def _tokens(
    body: dict[str, Any],
    requested_scopes: list[str],
    *,
    previous: str = "",
    require_scope: bool = True,
) -> dict[str, Any]:
    expected = checked_scopes(requested_scopes)
    granted = body.get("scope", None if require_scope else " ".join(expected))
    if not isinstance(granted, str) or sorted(granted.split()) != expected:
        raise DriveError("Google Drive permissions differ from requested capabilities")
    lifetime = body.get("expires_in")
    if (
        not isinstance(lifetime, (int, float))
        or isinstance(lifetime, bool)
        or not math.isfinite(lifetime)
        or not 0 < lifetime <= 86400
        or str(body.get("token_type", "")).lower() != "bearer"
    ):
        raise DriveError("Invalid Google token lifetime or type")
    return {
        "access_token": string(body.get("access_token"), 8192),
        "refresh_token": string(body.get("refresh_token", previous), 8192, empty=True),
        "expires_at": time.time() + lifetime,
        "scope": " ".join(expected),
        "token_type": "Bearer",
    }


def exchange_code(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
    requested_scopes: list[str],
    *,
    transport: httpx.BaseTransport | None = None,
    before_send: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    if not _PKCE.fullmatch(code_verifier):
        raise DriveError("Invalid OAuth challenge")
    with client(transport) as c:
        return _tokens(
            request(
                c,
                "POST",
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": string(client_id),
                    "client_secret": string(client_secret, 4096),
                    "redirect_uri": redirect(redirect_uri),
                    "code": string(code, 8192),
                    "code_verifier": code_verifier,
                },
                before_send=before_send,
            ),
            requested_scopes,
        )


def refresh_token(
    client_id: str,
    client_secret: str,
    refresh: str,
    requested_scopes: list[str],
    *,
    transport: httpx.BaseTransport | None = None,
    before_send: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    with client(transport) as c:
        return _tokens(
            request(
                c,
                "POST",
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": string(client_id),
                    "client_secret": string(client_secret, 4096),
                    "refresh_token": string(refresh, 8192),
                },
                before_send=before_send,
            ),
            requested_scopes,
            previous=refresh,
            require_scope=False,
        )


def revoke_token(
    token: str,
    *,
    transport: httpx.BaseTransport | None = None,
    before_send: Callable[[], Any] | None = None,
) -> None:
    with client(transport) as c:
        request(
            c,
            "POST",
            REVOKE_URL,
            data={"token": string(token, 8192)},
            before_send=before_send,
            empty_ok=True,
        )


def _file(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DriveError("Invalid Google Drive file metadata")
    result = {
        "id": identifier(value.get("id")),
        "name": string(value.get("name"), 255),
        "mimeType": string(value.get("mimeType"), 200),
        "trashed": value.get("trashed", False),
    }
    if type(result["trashed"]) is not bool:
        raise DriveError("Invalid Google Drive trash flag")
    if "size" in value:
        size = value["size"]
        if not isinstance(size, str) or not re.fullmatch(r"[0-9]{1,20}", size):
            raise DriveError("Invalid Google Drive file size")
        result["size"] = size
    if "modifiedTime" in value:
        result["modifiedTime"] = string(value["modifiedTime"], 80)
    parents = value.get("parents", [])
    if not isinstance(parents, list):
        raise DriveError("Invalid Google Drive parents")
    result["parents"] = [identifier(x) for x in parents]
    if len(result["parents"]) > 20:
        raise DriveError("Too many Google Drive parents")
    props = value.get("appProperties", {})
    if not isinstance(props, dict) or len(props) > 30:
        raise DriveError("Invalid Google Drive app properties")
    result["appProperties"] = {string(k, 100): string(v, 200) for k, v in props.items()}
    if "ownedByMe" in value:
        if type(value["ownedByMe"]) is not bool:
            raise DriveError("Invalid Google Drive owner flag")
        result["ownedByMe"] = value["ownedByMe"]
    capabilities = value.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise DriveError("Invalid Google Drive capabilities")
    if "canAddChildren" in capabilities:
        if type(capabilities["canAddChildren"]) is not bool:
            raise DriveError("Invalid Google Drive child capability")
        result["capabilities"] = {"canAddChildren": capabilities["canAddChildren"]}
    if "md5Checksum" in value:
        if not isinstance(value["md5Checksum"], str) or not re.fullmatch(
            r"[a-fA-F0-9]{32}", value["md5Checksum"]
        ):
            raise DriveError("Invalid Google Drive checksum")
        result["md5Checksum"] = value["md5Checksum"].lower()
    return result


class DriveClient:
    def __init__(
        self,
        token: str,
        *,
        before_send: Callable[[], Any] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.token, self.before_send, self.http = (
            string(token, 8192),
            before_send,
            client(transport),
        )

    def __enter__(self) -> DriveClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.http.close()

    def _call(self, method: str, url: str, **kwargs: Any) -> Any:
        return request(
            self.http, method, url, token=self.token, before_send=self.before_send, **kwargs
        )

    def about(self) -> dict[str, str]:
        body = self._call("GET", API_BASE + "/about", params={"fields": "user(emailAddress)"})
        user = body.get("user")
        if not isinstance(user, dict):
            raise DriveError("Google account missing")
        email = string(user.get("emailAddress"), 320)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise DriveError("Invalid Google account")
        return {"emailAddress": email}

    def list_files(
        self, parent: str = "root", *, page_token: str = "", limit: int = 50
    ) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise DriveError("Invalid Google Drive page size")
        params = {
            "q": "'" + identifier(parent) + "' in parents and trashed = false",
            "pageSize": str(limit),
            "fields": "nextPageToken,files(" + FIELDS + ")",
            "orderBy": "folder,name",
            "spaces": "drive",
        }
        if page_token:
            params["pageToken"] = string(page_token, 2048)
        body = self._call("GET", API_BASE + "/files", params=params)
        rows = body.get("files")
        if not isinstance(rows, list) or len(rows) > limit:
            raise DriveError("Google Drive page limit exceeded")
        return {
            "files": [_file(f) for f in rows],
            "next_page_token": string(body.get("nextPageToken", ""), 2048, empty=True),
        }

    def metadata(self, file_id: str) -> dict[str, Any]:
        return _file(
            self._call("GET", API_BASE + "/files/" + identifier(file_id), params={"fields": FIELDS})
        )

    def download(self, file_id: str, mime_type: str) -> bytes:
        file_id = identifier(file_id)
        if mime_type in EXPORTS:
            return cast(
                bytes,
                self._call(
                    "GET",
                    API_BASE + "/files/" + file_id + "/export",
                    binary=True,
                    params={"mimeType": EXPORTS[mime_type][0]},
                ),
            )
        if mime_type.startswith("application/vnd.google-apps."):
            raise DriveError("Google Workspace file type is not supported")
        return cast(
            bytes,
            self._call("GET", API_BASE + "/files/" + file_id, params={"alt": "media"}, binary=True),
        )

    def generate_ids(self, count: int = 1) -> list[str]:
        if type(count) is not int or not 1 <= count <= 10:
            raise DriveError("Invalid Google Drive identity count")
        body = self._call(
            "GET",
            API_BASE + "/files/generateIds",
            params={"count": count, "space": "drive", "type": "files"},
        )
        values = body.get("ids")
        if not isinstance(values, list) or len(values) != count:
            raise DriveError("Invalid Google Drive identities")
        checked = [identifier(x) for x in values]
        if len(set(checked)) != count:
            raise DriveError("Invalid Google Drive identities")
        return checked

    def create_folder(
        self, file_id: str, name: str, app_properties: dict[str, str]
    ) -> dict[str, Any]:
        return _file(
            self._call(
                "POST",
                API_BASE + "/files",
                params={"fields": FIELDS},
                document={
                    "id": identifier(file_id),
                    "name": string(name, 255),
                    "mimeType": FOLDER,
                    "appProperties": _properties(app_properties),
                },
            )
        )

    def upload(
        self,
        file_id: str,
        parent: str,
        name: str,
        content: bytes,
        mime_type: str,
        app_properties: dict[str, str],
    ) -> dict[str, Any]:
        if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_BYTES:
            raise DriveError("Google Drive upload limit exceeded")
        mime_type = string(mime_type, 200)
        if not re.fullmatch(r"[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+", mime_type):
            raise DriveError("Invalid upload type")
        boundary = "obdaai_" + secrets.token_hex(24)
        metadata = json.dumps(
            {
                "id": identifier(file_id),
                "name": string(name, 255),
                "parents": [identifier(parent)],
                "mimeType": mime_type,
                "appProperties": _properties(app_properties),
            }
        ).encode()
        raw = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
            + metadata
            + f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n".encode()
            + content
            + f"\r\n--{boundary}--\r\n".encode()
        )
        return _file(
            self._call(
                "POST",
                UPLOAD_URL,
                params={"uploadType": "multipart", "fields": FIELDS},
                content=raw,
                content_type="multipart/related; boundary=" + boundary,
            )
        )


def _properties(values: dict[str, str]) -> dict[str, str]:
    if not isinstance(values, dict) or not 1 <= len(values) <= 10:
        raise DriveError("App ownership metadata required")
    if any(not re.fullmatch(r"obdaai_[a-z_]{1,40}", k) for k in values):
        raise DriveError("Invalid app ownership metadata")
    return {k: string(v, 200) for k, v in values.items()}
