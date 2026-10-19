"""Human-only configuration of one operator-pinned local Proton Bridge adapter."""

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import Field, model_validator

from hub.action_api import StrictInput, digest, encode
from hub.agent_models import AgentPolicy, AgentPolicyEvent
from hub.agent_tools import Rules
from hub.config import Settings, read_secret
from hub.db_locks import ownership_lock
from hub.integration_api import approved
from hub.integration_transport import proton_catalog_pending
from hub.integration_write_adapters import mcp_catalog
from hub.integration_writes import registry_lock
from hub.integrations import Integration
from hub.knowledge_api import Auth
from hub.mcp_client import schema_digest
from hub.provider_settings import decrypt

READ_TOOLS = frozenset(
    {
        "list_folders",
        "list_emails",
        "search_emails",
        "read_email",
        "get_status",
        "daily_digest",
        "get_thread",
        "list_attachments",
    }
)


class BridgeInput(StrictInput):
    name: str = Field(min_length=1, max_length=80, strict=True)
    username: str = Field(min_length=1, max_length=254, strict=True)
    password: str | None = Field(default=None, max_length=4096, repr=False, strict=True)
    expected_revision: int = Field(ge=1, strict=True)
    request_id: UUID
    enable_reads: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def valid_credentials(self) -> "BridgeInput":
        if not self.name.strip() or self.username != self.username.strip():
            raise ValueError("Name and username required")
        if any(ord(c) < 32 or ord(c) == 127 for c in self.username + (self.password or "")):
            raise ValueError("Invalid credential characters")
        return self


def enabled(cfg: Settings) -> bool:
    return bool(
        cfg.proton_bridge_control_url in {"http://127.0.0.1:18765", "http://localhost:18765"}
        and cfg.proton_bridge_control_token_file
        and cfg.proton_bridge_integration_id
    )


def control(cfg: Settings, body: dict[str, Any] | None = None) -> dict[str, Any]:
    if not enabled(cfg):
        raise ValueError("Bridge configuration disabled")
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=40) as client:
        response = client.request(
            "POST" if body is not None else "GET",
            cfg.proton_bridge_control_url + "/v1/configuration",
            headers={
                "Authorization": "Bearer " + read_secret(cfg.proton_bridge_control_token_file)
            },
            json=body,
        )
    if response.status_code != 200 or len(response.content) > 4096:
        raise ValueError("Bridge configuration unavailable")
    data = response.json()
    if (
        not isinstance(data, dict)
        or type(data.get("revision")) is not int
        or data["revision"] < 0
        or not isinstance(data.get("username"), str)
        or len(data["username"]) > 254
        or type(data.get("connected")) is not bool
    ):
        raise ValueError("Invalid Bridge control response")
    return data


def pinned_profile(db: Any, cfg: Settings) -> Integration:
    row: Integration | None = db.get(Integration, cfg.proton_bridge_integration_id)
    if (
        not row
        or row.kind != "mcp"
        or not approved(cfg, row)
        or not cfg.proton_bridge_mcp_url
        or json.loads(row.config).get("url") != cfg.proton_bridge_mcp_url
    ):
        raise HTTPException(503, "Proton-Profil ist nicht vom Betreiber eingerichtet")
    return row


def view(db: Any, cfg: Settings, state: dict[str, Any] | None = None) -> dict[str, Any]:
    if not enabled(cfg):
        return {
            "available": False,
            "integration_id": None,
            "name": "Proton Mail",
            "username": "",
            "revision": 0,
            "connected": False,
            "enable_reads": False,
            "message": "Proton Bridge wurde vom Betreiber noch nicht eingerichtet.",
        }
    row = pinned_profile(db, cfg)
    checked = json.loads(row.last_check) if row.last_check else {}
    policy = db.get(AgentPolicy, row.id)
    rules = Rules.model_validate_json(policy.rules) if policy else Rules()
    reads = bool(
        row.enabled
        and policy
        and policy.profile_revision == row.revision
        and rules.enabled
        and rules.mcp_read_tools
        and not rules.mcp
    )
    try:
        state = state or control(cfg)
    except Exception:
        state = {"username": "", "connected": False}
    connected = bool(
        state["connected"]
        and row.enabled
        and checked.get("revision") == row.revision
        and checked.get("status") == "succeeded"
    )
    return {
        "available": True,
        "integration_id": row.id,
        "name": row.name,
        "username": state["username"],
        "revision": row.revision,
        "connected": connected,
        "enable_reads": reads,
        "message": "Postfach lokal verbunden; Versand und Änderungen gesperrt."
        if connected
        else "Bridge-Zugangsdaten eingeben und Verbindung prüfen.",
    }


def catalog_ready(
    cfg: Settings, config: dict[str, Any], secret: str, before_attempt: Callable[[], None]
) -> dict[str, Any]:
    """Only retry read-only discovery while the observer installs its bounded lease."""
    deadline = time.monotonic() + 25
    first = True
    while True:
        if not first and time.monotonic() >= deadline:
            raise TimeoutError("Proton catalog readiness window elapsed")
        first = False
        before_attempt()
        try:
            return mcp_catalog(cfg, config, secret)
        except httpx.ConnectError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(1, remaining))


def install_proton_bridge_setup(app: FastAPI, cfg: Settings, factory: Any) -> None:
    @app.get("/api/integrations/proton-bridge-setup")
    def get_setup(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return view(db, cfg)

    @app.post("/api/integrations/proton-bridge-setup")
    def save_setup(body: BridgeInput, auth: Auth) -> dict[str, Any]:
        if not enabled(cfg):
            raise HTTPException(503, "Proton Bridge ist nicht eingerichtet")
        if not cfg.integration_targets_enabled:
            raise HTTPException(403, "Verbindungen zu Integrationen sind am Server ausgeschaltet")
        request_id = str(body.request_id)
        try:
            token = read_secret(cfg.proton_bridge_control_token_file)
            fingerprint = hmac.new(
                token.encode(), body.model_dump_json().encode(), hashlib.sha256
            ).hexdigest()
        except Exception:
            raise HTTPException(503, "Proton-Konfiguration nicht verfügbar") from None
        with factory() as db:
            ownership_lock(db)
            registry_lock(db)
            row = pinned_profile(db, cfg)
            checked = json.loads(row.last_check) if row.last_check else {}
            previous = checked.get("proton_setup", {})
            if previous.get("request_id") == request_id:
                if previous.get("fingerprint") != fingerprint:
                    raise HTTPException(409, "Anfrage-ID bereits anders verwendet")
                if checked.get("status") == "succeeded":
                    return view(db, cfg)
                raise HTTPException(
                    409, "Vorheriger Versuch nicht abgeschlossen; keine automatische Wiederholung"
                )
            if row.revision != body.expected_revision:
                raise HTTPException(409, "Integration geändert; neu laden")
            # Revoke the old account's jobs before any external credential mutation.
            row.enabled, row.writes_enabled = False, False
            row.revision += 1
            revision = row.revision
            marker = {"request_id": request_id, "fingerprint": fingerprint, "created": time.time()}
            row.last_check = encode(
                {"revision": revision, "status": "pending", "proton_setup": marker}
            )
            db.commit()

        def pending_row(db: Any) -> Integration:
            current_row = pinned_profile(db, cfg)
            current = json.loads(current_row.last_check) if current_row.last_check else {}
            if (
                current_row.revision != revision
                or not proton_catalog_pending(cfg, current_row)
                or current.get("proton_setup") != marker
            ):
                raise ValueError("Profile or catalog setup lease changed")
            return current_row

        def pending_boundary() -> None:
            with factory() as db:
                pending_row(db)

        broker_applied = False
        try:
            state = control(cfg)
            pending_boundary()
            state = control(
                cfg,
                {
                    "username": body.username,
                    "password": body.password or None,
                    "expected_revision": state["revision"],
                    "request_id": request_id,
                },
            )
            broker_applied = True
            with factory() as db:
                row = pending_row(db)
                config = json.loads(row.config)
                secret = (
                    decrypt(cfg, "integration:" + row.id, row.encrypted_secret)
                    if row.encrypted_secret
                    else ""
                )
            # Readiness waits must not retain global mutation locks: revocation
            # remains available before every probe and final authorization.
            catalog = catalog_ready(cfg, config, secret, pending_boundary)
            with factory() as db:
                ownership_lock(db)
                registry_lock(db)
                row = pending_row(db)
                if catalog.get("label") != "LOCAL_ONLY":
                    raise ValueError("Invalid catalog label")
                tools = {t["name"]: schema_digest(t["input_schema"]) for t in catalog["tools"]}
                if not READ_TOOLS <= tools.keys():
                    raise ValueError("Required read tools missing")
                row.name = body.name.strip()
                row.last_check = encode(
                    {
                        "revision": revision,
                        "status": "succeeded",
                        "at": time.time(),
                        "result": catalog,
                        "proton_setup": marker,
                    }
                )
                row.enabled, row.writes_enabled = body.enable_reads, False
                rules = Rules(
                    enabled=body.enable_reads,
                    autonomous=False,
                    private_data_to_target=False,
                    mcp=False,
                    max_effects=0,
                    mcp_read_tools={name: tools[name] for name in sorted(READ_TOOLS)}
                    if body.enable_reads
                    else {},
                )
                policy = db.get(AgentPolicy, row.id)
                if policy is None:
                    policy = AgentPolicy(
                        integration_id=row.id,
                        profile_revision=revision,
                        revision=1,
                        rules=encode(rules.model_dump()),
                    )
                    db.add(policy)
                else:
                    policy.profile_revision, policy.rules = revision, encode(rules.model_dump())
                    policy.revision += 1
                document = encode(
                    {
                        "revision": policy.revision,
                        "profile_revision": revision,
                        "rules": rules.model_dump(),
                        "source": "authenticated_human_proton_setup",
                    }
                )
                db.add(
                    AgentPolicyEvent(
                        integration_id=row.id, document=document, sha256=digest(document)
                    )
                )
                db.commit()
                return view(db, cfg, state)
        except Exception:
            # Preserve the durable pending marker and disabled profile for reconciliation.
            raise HTTPException(
                502,
                "Bridge-Zugang wurde gespeichert; die Prüfung des Postfachdienstes ist nicht "
                "abgeschlossen. Profil bleibt gesperrt; keine automatische Wiederholung."
                if broker_applied
                else "Bridge-Verbindung fehlgeschlagen; Profil bleibt gesperrt. "
                "Zugangsdaten und Bridge-Anmeldung prüfen.",
            ) from None
