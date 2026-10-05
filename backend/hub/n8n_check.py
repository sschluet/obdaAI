"""Operator-only inactive NoOp check. No workflow activation or execution API."""

import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from hub.n8n_drafts import validate_connection_draft

ORIGIN = "https://n8n.schlueterbusch.de"
MAX_RESPONSE = 1_000_000


class CheckError(RuntimeError):
    pass


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def remote_check(workflow: dict[str, Any], payload: dict[str, Any]) -> str:
    wid = workflow.get("id")
    if not isinstance(wid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", wid):
        raise CheckError("Invalid workflow identity")
    if workflow.get("active") is not False or workflow.get("isArchived", False):
        raise CheckError("Workflow must remain inactive and unarchived")
    if workflow.get("activeVersionId") is not None:
        raise CheckError("Unexpected published workflow version")
    for field in ("name", "nodes", "connections", "settings"):
        if workflow.get(field) != payload[field]:
            raise CheckError("Workflow drift; operator review required")
    if workflow.get("pinData") or workflow.get("staticData"):
        raise CheckError("Unexpected workflow data")
    return wid


class ConnectionCheck:
    def __init__(self, client: httpx.Client, key: str) -> None:
        if not key.strip() or "\n" in key or "\r" in key:
            raise CheckError("Invalid API key")
        self.client, self.key = client, key

    def request(self, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            with self.client.stream(
                "GET" if payload is None else "POST",
                ORIGIN + "/api/v1/" + path,
                headers={"X-N8N-API-KEY": self.key},
                json=payload,
                follow_redirects=False,
                timeout=15,
            ) as response:
                if response.status_code != 200:
                    raise CheckError(f"n8n HTTP {response.status_code}; no automatic retry")
                data = bytearray()
                for part in response.iter_bytes():
                    data.extend(part)
                    if len(data) > MAX_RESPONSE:
                        raise CheckError("n8n response exceeds limit")
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise CheckError("Invalid n8n response")
                return result
        except (httpx.HTTPError, ValueError):
            raise CheckError("n8n transport or response error; reconcile before retry") from None

    def find(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        params: dict[str, str | int] = {
            "name": payload["name"],
            "limit": 100,
            "excludePinnedData": "true",
        }
        found: list[dict[str, Any]] = []
        for _ in range(10):
            page = self.request("workflows?" + str(httpx.QueryParams(params)))
            rows = page.get("data")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise CheckError("Invalid workflow listing")
            found.extend(row for row in rows if row.get("name") == payload["name"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
            if not isinstance(cursor, str) or len(cursor) > 2048:
                raise CheckError("Invalid workflow cursor")
            params["cursor"] = cursor
        else:
            raise CheckError("Workflow listing incomplete; no mutation")
        if len(found) > 1:
            raise CheckError("Ambiguous workflow identity; no mutation")
        return found[0] if found else None

    def ensure(
        self, review: dict[str, Any], journal: Path, *, approved: bool = False
    ) -> dict[str, Any]:
        if journal.is_symlink():
            raise CheckError("Journal symlinks are forbidden")
        journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = journal.with_suffix(journal.suffix + ".lock")
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as held:
            try:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CheckError("Another operator check is active; no mutation") from None
            return self._ensure(review, journal, approved=approved)

    def _ensure(self, review: dict[str, Any], journal: Path, *, approved: bool) -> dict[str, Any]:
        payload = review["payload"]
        validate_connection_draft(
            payload, review["task_id"], review["revision"], review["spec_sha256"]
        )
        expected = fingerprint(payload)
        record = json.loads(journal.read_text()) if journal.exists() else None
        if record is not None and not isinstance(record, dict):
            raise CheckError("Invalid operator journal")
        if record is not None and record.get("payload_sha256") != expected:
            raise CheckError("Journal belongs to another reviewed draft")
        if record and record.get("workflow_id"):
            wid = record["workflow_id"]
            if not isinstance(wid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", wid):
                raise CheckError("Invalid journal workflow identity")
            existing: dict[str, Any] | None = self.request("workflows/" + wid)
        else:
            existing = self.find(payload)
        if existing is None:
            if record:
                raise CheckError("Creation outcome uncertain; no repeated POST")
            if not approved:
                raise CheckError("Explicit approval required before creation")
            # Persist intent before I/O. A crash or unknown response cannot trigger a second POST.
            self.save(journal, {"payload_sha256": expected, "status": "prepared"})
            existing = self.request("workflows", payload=payload)
            wid = remote_check(existing, payload)
            self.save(
                journal, {"payload_sha256": expected, "status": "created", "workflow_id": wid}
            )
        wid = remote_check(existing, payload)
        verified = self.request("workflows/" + wid)
        remote_check(verified, payload)
        receipt = {
            "payload_sha256": expected,
            "workflow_id": wid,
            "status": "verified",
            "inactive": True,
            "executes_task": False,
        }
        self.save(journal, receipt)
        return receipt

    @staticmethod
    def save(path: Path, value: dict[str, Any]) -> None:
        if path.is_symlink():
            raise CheckError("Journal symlinks are forbidden")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
