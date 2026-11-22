"""Human GoogleDrive OAuth setup with session-bound, single-attempt private credentials."""

import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from cryptography.exceptions import InvalidTag
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import Field, model_validator
from sqlalchemy import Float, Index, Integer, String, Text, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from hub import google_drive_client
from hub.action_api import StrictInput, digest, encode
from hub.auth import token_hash
from hub.config import Settings, read_secret
from hub.db import Base, LoginSession, new_id
from hub.db_locks import ownership_lock
from hub.integration_writes import registry_lock
from hub.integrations import Integration
from hub.knowledge_api import Auth
from hub.provider_settings import decrypt, encrypt

CALLBACK = "/api/integrations/google-drive/callback"
COOKIE = "hub_google_drive_oauth"
MARKER = "native_google_drive_v1"


class GoogleDriveOAuthAttempt(Base):
    __tablename__ = "google_drive_oauth_attempts"
    __table_args__ = (
        Index(
            "one_google_drive_refresh_per_revision",
            "integration_id",
            "profile_revision",
            unique=True,
            sqlite_where=text("operation = 'refresh' AND status = 'dispatching'"),
            postgresql_where=text("operation = 'refresh' AND status = 'dispatching'"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(16))
    integration_id: Mapped[str] = mapped_column(String(36), index=True)
    profile_revision: Mapped[int] = mapped_column(Integer)
    session_hash: Mapped[str] = mapped_column(String(64))
    state_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    cookie_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    encrypted_verifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    created: Mapped[float] = mapped_column(Float, default=time.time)
    expires: Mapped[float] = mapped_column(Float)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)


class SetupInput(StrictInput):
    integration_id: UUID | None = None
    name: str = Field(min_length=1, max_length=80, strict=True)
    client_id: str = Field(min_length=10, max_length=256, strict=True)
    client_secret: str | None = Field(default=None, max_length=4096, repr=False, strict=True)
    expected_revision: int | None = Field(default=None, ge=1, strict=True)
    request_id: UUID
    enable_source: bool = Field(default=False, strict=True)
    enable_storage: bool = Field(default=False, strict=True)
    source_folder_id: str = Field(default="root", max_length=200, strict=True)

    @model_validator(mode="after")
    def valid(self) -> "SetupInput":
        if not self.name.strip() or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{4,220}\.apps\.googleusercontent\.com", self.client_id
        ):
            raise ValueError("Google Web OAuth client ID required")
        if self.client_secret and any(not 33 <= ord(c) <= 126 for c in self.client_secret):
            raise ValueError("Invalid OAuth client secret")
        if bool(self.integration_id) != bool(self.expected_revision):
            raise ValueError("Existing integrations require their current revision")
        google_drive_client.identifier(self.source_folder_id)
        return self


class AuthorizeInput(StrictInput):
    expected_revision: int = Field(ge=1, strict=True)
    request_id: UUID


class DisconnectInput(StrictInput):
    expected_revision: int = Field(ge=1, strict=True)
    revoke_google: bool = Field(default=False, strict=True)


def redirect_uri(cfg: Settings) -> str:
    origin = cfg.origin.rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"https", "http"}
        or parsed.scheme == "http"
        and parsed.hostname != "127.0.0.1"
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or "\\" in origin
    ):
        raise ValueError("A fixed HTTPS origin or local development origin is required")
    return origin + CALLBACK


def credentials(cfg: Settings, row: Integration) -> dict[str, Any]:
    if row.kind != "google_drive" or not row.encrypted_secret:
        raise ValueError("GoogleDrive credentials missing")
    try:
        value = json.loads(decrypt(cfg, "integration:" + row.id, row.encrypted_secret))
        if not isinstance(value, dict):
            raise ValueError("Invalid credential document")
        return value
    except (InvalidTag, ValueError, TypeError, OSError, RecursionError):
        raise ValueError("Google Drive credentials unavailable") from None


def configured_scopes(config: dict[str, Any]) -> list[str]:
    return google_drive_client.scopes(
        config.get("enable_source") is True, config.get("enable_storage") is True
    )


def ready(cfg: Settings, row: Integration, capability: str = "source") -> bool:
    try:
        config = json.loads(row.config)
        expected = configured_scopes(config)
        if not (
            cfg.integration_targets_enabled
            and row.kind == "google_drive"
            and row.enabled
            and row.encrypted_secret
            and config.get("url") == google_drive_client.API_BASE
            and config.get("auth") == "oauth"
            and config.get("google_drive_marker") == MARKER
            and config.get("connected") is True
            and expected
            and capability in {"source", "storage"}
            and config.get("enable_" + capability) is True
            and (capability != "storage" or row.writes_enabled)
        ):
            return False
        data = credentials(cfg, row)
        return bool(
            data.get("scope") == " ".join(sorted(expected))
            and config.get("scope") == data.get("scope")
            and data.get("token_type") == "Bearer"
            and data.get("refresh_token")
            and data.get("account_email") == config.get("account_email")
            and data.get("account_email")
        )
    except (ValueError, TypeError, AttributeError, OSError):
        return False


def authority_guard(
    factory: Any,
    cfg: Settings,
    integration_id: str,
    expected_revision: int,
    capability: str = "source",
) -> Callable[[], None]:
    def guard() -> None:
        with factory() as db:
            row = db.get(Integration, integration_id)
            if not row or row.revision != expected_revision or not ready(cfg, row, capability):
                raise PermissionError("Google Drive authority changed")

    return guard


def _lock(db: Session) -> None:
    ownership_lock(db)
    registry_lock(db)


def _profile(db: Session, integration_id: str) -> Integration:
    row = db.get(Integration, integration_id)
    if not row or row.kind != "google_drive":
        raise HTTPException(404, "GoogleDrive-Verbindung fehlt")
    return row


def _store(cfg: Settings, row: Integration, data: dict[str, Any]) -> None:
    row.encrypted_secret = encrypt(cfg, "integration:" + row.id, encode(data))


def _fingerprint(cfg: Settings, document: str) -> str:
    return hmac.new(
        read_secret(cfg.secrets_key_file).encode(), document.encode(), hashlib.sha256
    ).hexdigest()


def _invalidate_attempts(db: Session, integration_id: str) -> None:
    db.execute(
        update(GoogleDriveOAuthAttempt)
        .where(
            GoogleDriveOAuthAttempt.integration_id == integration_id,
            GoogleDriveOAuthAttempt.status == "ready",
        )
        .values(status="superseded", encrypted_verifier=None, finished=time.time())
    )


def _view(cfg: Settings, row: Integration | None = None) -> dict[str, Any]:
    try:
        data = credentials(cfg, row) if row and row.encrypted_secret else {}
        config = json.loads(row.config) if row else {}
    except (ValueError, TypeError, OSError, RecursionError):
        raise HTTPException(
            503,
            "Google-Drive-Zugangsdaten nicht verfügbar. Serververschlüsselung prüfen "
            "und die Verbindung bei Bedarf erneut einrichten.",
        ) from None
    return {
        "available": bool(cfg.secrets_key_file),
        "integration_id": row.id if row else None,
        "revision": row.revision if row else 0,
        "name": row.name if row else "Google Drive",
        "client_id": data.get("client_id", ""),
        "client_secret_saved": bool(data.get("client_secret")),
        "configured": bool(data.get("client_id") and data.get("client_secret")),
        "connected": bool(config.get("connected") and data.get("refresh_token")),
        "enabled": bool(row and row.enabled),
        "enable_source": bool(config.get("enable_source")),
        "enable_storage": bool(config.get("enable_storage")),
        "source_folder_id": config.get("source_folder_id", "root"),
        "storage_folder_id": config.get("storage_folder_id", ""),
        "account_email": config.get("account_email", ""),
        "reauthorization_required": config.get("reauthorization_required") is True,
        "redirect_uri": redirect_uri(cfg),
        "scopes": configured_scopes(config),
        "network_ready": cfg.integration_targets_enabled,
        "message": "Erneute Anmeldung bei Google erforderlich; keine automatische Wiederholung."
        if config.get("reauthorization_required")
        else "Google Drive ist verbunden. Quellen und Ablage sind getrennt konfigurierbar."
        if config.get("connected")
        else "OAuth-Webclient speichern und bei Google verbinden.",
    }


def _live_session(db: Session, session_hash: str) -> bool:
    login = db.get(LoginSession, session_hash)
    return bool(login and login.expires > time.time())


def _terminal(db: Session, attempt: GoogleDriveOAuthAttempt, status: str) -> None:
    attempt.status, attempt.finished, attempt.encrypted_verifier = status, time.time(), None
    row = db.get(Integration, attempt.integration_id)
    if row and row.revision == attempt.profile_revision:
        config = json.loads(row.config)
        config.pop("oauth_pending_until", None)
        row.config = encode(config)


def _result(cfg: Settings, result: str, integration_id: str = "") -> RedirectResponse:
    flags = {"google_drive_result": "connected" if result == "connected" else "failed"}
    if integration_id:
        flags["google_drive_integration"] = integration_id
    response = RedirectResponse(
        "/?view=Einstellungen&settingsTab=Integrationen#" + urlencode(flags), status_code=303
    )
    response.delete_cookie(
        COOKIE, path=CALLBACK, secure=cfg.secure_cookie, httponly=True, samesite="lax"
    )
    return response


def install_google_drive_setup(app: FastAPI, cfg: Settings, factory: Any) -> None:
    @app.get("/api/integrations/google-drive/setup")
    def metadata(auth: Auth, integration_id: UUID | None = None) -> dict[str, Any]:
        with factory() as db:
            return _view(cfg, _profile(db, str(integration_id)) if integration_id else None)

    @app.get("/api/integrations/google-drive/{integration_id}/status")
    def status(integration_id: UUID, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return _view(cfg, _profile(db, str(integration_id)))

    @app.post("/api/integrations/google-drive/setup")
    def save(body: SetupInput, auth: Auth) -> dict[str, Any]:
        try:
            fingerprint = _fingerprint(cfg, body.model_dump_json() + auth.token_hash)
            redirect_uri(cfg)
        except (ValueError, OSError):
            raise HTTPException(
                503, "Serververschlüsselung oder feste Rückleitungsadresse fehlt"
            ) from None
        with factory() as db:
            _lock(db)
            previous = db.scalar(
                select(GoogleDriveOAuthAttempt).where(
                    GoogleDriveOAuthAttempt.request_id == str(body.request_id)
                )
            )
            if previous:
                if previous.operation != "setup" or previous.request_digest != fingerprint:
                    raise HTTPException(409, "Anfrage-ID bereits anders verwendet")
                cached = _profile(db, previous.integration_id)
                if cached.revision != previous.profile_revision:
                    raise HTTPException(409, "Gespeicherte Anfrage inzwischen überholt")
                return _view(cfg, cached)
            row = _profile(db, str(body.integration_id)) if body.integration_id else None
            if row and row.revision != body.expected_revision:
                raise HTTPException(409, "GoogleDrive-Verbindung geändert; neu laden")
            old = credentials(cfg, row) if row and row.encrypted_secret else {}
            secret = body.client_secret or (
                old.get("client_secret") if old.get("client_id") == body.client_id else ""
            )
            if not secret:
                raise HTTPException(422, "Client-Secret für diesen OAuth-Client erforderlich")
            if row is None:
                row = Integration(
                    name=body.name.strip(),
                    kind="google_drive",
                    config="{}",
                    enabled=False,
                    writes_enabled=False,
                )
                db.add(row)
                db.flush()
            else:
                row.revision += 1
                _invalidate_attempts(db, row.id)
            row.name, row.enabled, row.writes_enabled = body.name.strip(), False, False
            row.config = encode(
                {
                    "kind": "google_drive",
                    "url": google_drive_client.API_BASE,
                    "auth": "oauth",
                    "google_drive_marker": MARKER,
                    "scope": " ".join(
                        sorted(google_drive_client.scopes(body.enable_source, body.enable_storage))
                    ),
                    "connected": False,
                    "account_email": "",
                    "enable_source": body.enable_source,
                    "enable_storage": body.enable_storage,
                    "source_folder_id": body.source_folder_id,
                    "storage_folder_id": "",
                }
            )
            row.last_check = None
            _store(cfg, row, {"client_id": body.client_id, "client_secret": secret})
            db.add(
                GoogleDriveOAuthAttempt(
                    request_id=str(body.request_id),
                    request_digest=fingerprint,
                    operation="setup",
                    integration_id=row.id,
                    profile_revision=row.revision,
                    session_hash=auth.token_hash,
                    status="succeeded",
                    expires=time.time(),
                    finished=time.time(),
                )
            )
            db.commit()
            return _view(cfg, row)

    @app.post("/api/integrations/google-drive/{integration_id}/authorize")
    def authorize(
        integration_id: UUID, body: AuthorizeInput, auth: Auth, response: Response
    ) -> dict[str, Any]:
        if not cfg.integration_targets_enabled:
            raise HTTPException(403, "GoogleDrive-Netzzugang ist am Server ausgeschaltet")
        with factory() as db:
            _lock(db)
            row = _profile(db, str(integration_id))
            if not configured_scopes(json.loads(row.config)):
                raise HTTPException(422, "Zuerst Quelle oder Ablage auswählen")
            fingerprint = _fingerprint(
                cfg, encode({"id": row.id, **body.model_dump(mode="json")}) + auth.token_hash
            )
            attempt = db.scalar(
                select(GoogleDriveOAuthAttempt).where(
                    GoogleDriveOAuthAttempt.request_id == str(body.request_id)
                )
            )
            if attempt:
                if (
                    attempt.operation != "oauth"
                    or attempt.request_digest != fingerprint
                    or attempt.session_hash != auth.token_hash
                    or attempt.profile_revision != row.revision
                    or attempt.status != "ready"
                    or attempt.expires <= time.time()
                    or not attempt.encrypted_verifier
                ):
                    raise HTTPException(409, "Anmeldung verbraucht, geändert oder abgelaufen")
                private = json.loads(
                    decrypt(cfg, "google_drive-oauth:" + attempt.id, attempt.encrypted_verifier)
                )
            else:
                if row.revision != body.expected_revision:
                    raise HTTPException(409, "GoogleDrive-Verbindung geändert; neu laden")
                data = credentials(cfg, row)
                if not data.get("client_id") or not data.get("client_secret"):
                    raise HTTPException(409, "Zuerst OAuth-Client speichern")
                _invalidate_attempts(db, row.id)
                row.enabled, row.writes_enabled, row.last_check = False, False, None
                row.revision += 1
                config = json.loads(row.config)
                config.update(
                    connected=False,
                    account_email="",
                    storage_folder_id="",
                    oauth_pending_until=time.time() + 600,
                )
                row.config = encode(config)
                _store(
                    cfg,
                    row,
                    {"client_id": data["client_id"], "client_secret": data["client_secret"]},
                )
                private = {
                    "state": secrets.token_urlsafe(48),
                    "verifier": secrets.token_urlsafe(64),
                    "cookie": secrets.token_urlsafe(48),
                }
                attempt = GoogleDriveOAuthAttempt(
                    id=new_id(),
                    request_id=str(body.request_id),
                    request_digest=fingerprint,
                    operation="oauth",
                    integration_id=row.id,
                    profile_revision=row.revision,
                    session_hash=auth.token_hash,
                    state_hash=token_hash(private["state"]),
                    cookie_hash=token_hash(private["cookie"]),
                    status="ready",
                    expires=time.time() + 600,
                )
                attempt.encrypted_verifier = encrypt(
                    cfg, "google_drive-oauth:" + attempt.id, encode(private)
                )
                db.add(attempt)
                db.commit()
            data = credentials(cfg, row)
            url = google_drive_client.authorization_url(
                data["client_id"],
                redirect_uri(cfg),
                private["state"],
                private["verifier"],
                configured_scopes(json.loads(row.config)),
            )
            response.set_cookie(
                COOKIE,
                private["cookie"],
                max_age=max(1, int(attempt.expires - time.time())),
                path=CALLBACK,
                secure=cfg.secure_cookie,
                httponly=True,
                samesite="lax",
            )
            return {
                "auth_url": url,
                "authorization_url": url,
                "expires_at": attempt.expires,
                "revision": row.revision,
            }

    @app.get(CALLBACK)
    def callback(request: Request, state: str = "", code: str = "", error: str = "") -> Response:
        # OAuth's narrowly scoped Lax cookie continues the original still-live
        # session when its ordinary Strict cookie is absent after Google navigation.
        if not 32 <= len(state) <= 512:
            return _result(cfg, "failed")
        with factory() as db:
            _lock(db)
            attempt = db.scalar(
                select(GoogleDriveOAuthAttempt).where(
                    GoogleDriveOAuthAttempt.state_hash == token_hash(state)
                )
            )
            if not attempt or attempt.operation != "oauth" or attempt.status != "ready":
                return _result(cfg, "failed")
            original = token_hash(request.cookies.get("hub_session", ""))
            continuation = token_hash(request.cookies.get(COOKIE, ""))
            session_is_live = _live_session(db, attempt.session_hash)
            authorized = session_is_live and (
                hmac.compare_digest(original, attempt.session_hash)
                or bool(
                    attempt.cookie_hash and hmac.compare_digest(continuation, attempt.cookie_hash)
                )
            )
            if not authorized:
                if not session_is_live:
                    _terminal(db, attempt, "failed")
                    db.commit()
                return _result(cfg, "failed")
            if len(code) > 4096 or len(error) > 128:
                _terminal(db, attempt, "failed")
                db.commit()
                return _result(cfg, "failed", attempt.integration_id)
            row = db.get(Integration, attempt.integration_id)
            if (
                attempt.expires <= time.time()
                or not row
                or row.revision != attempt.profile_revision
                or not attempt.encrypted_verifier
                or not cfg.integration_targets_enabled
            ):
                _terminal(db, attempt, "failed")
                db.commit()
                return _result(cfg, "failed", attempt.integration_id)
            if error or not code:
                _terminal(db, attempt, "denied" if error else "failed")
                db.commit()
                return _result(cfg, "denied" if error else "failed", row.id)
            private = json.loads(
                decrypt(cfg, "google_drive-oauth:" + attempt.id, attempt.encrypted_verifier)
            )
            data = credentials(cfg, row)
            expected_scopes = configured_scopes(json.loads(row.config))
            claimed = db.execute(
                update(GoogleDriveOAuthAttempt)
                .where(
                    GoogleDriveOAuthAttempt.id == attempt.id,
                    GoogleDriveOAuthAttempt.status == "ready",
                )
                .values(status="dispatching", encrypted_verifier=None)
            )
            if claimed.rowcount != 1:
                db.rollback()
                return _result(cfg, "failed", row.id)
            attempt_id, profile_id, revision = attempt.id, row.id, row.revision
            db.commit()

        def boundary() -> None:
            with factory() as db:
                active = db.get(GoogleDriveOAuthAttempt, attempt_id)
                row = db.get(Integration, profile_id)
                if (
                    not active
                    or active.status != "dispatching"
                    or not _live_session(db, active.session_hash)
                    or not row
                    or row.revision != revision
                    or not cfg.integration_targets_enabled
                    or json.loads(row.config).get("oauth_pending_until", 0) <= time.time()
                ):
                    raise PermissionError("GoogleDrive authorization changed")

        try:
            boundary()
            tokens = google_drive_client.exchange_code(
                data["client_id"],
                data["client_secret"],
                redirect_uri(cfg),
                code,
                private["verifier"],
                expected_scopes,
                before_send=boundary,
            )
            if (
                not tokens.get("refresh_token")
                or tokens.get("scope") != " ".join(sorted(expected_scopes))
                or tokens.get("token_type") != "Bearer"
            ):
                raise ValueError("Offline read-only OAuth credentials required")
            with google_drive_client.DriveClient(
                tokens["access_token"], before_send=boundary
            ) as client:
                account = client.about()["emailAddress"]
            with factory() as db:
                _lock(db)
                boundary()
                row = _profile(db, profile_id)
                attempt = db.get(GoogleDriveOAuthAttempt, attempt_id)
                assert attempt
                config = json.loads(row.config)
                config.update(connected=True, account_email=account, reauthorization_required=False)
                config.pop("oauth_pending_until", None)
                row.config = encode(config)
                _store(
                    cfg,
                    row,
                    {
                        "client_id": data["client_id"],
                        "client_secret": data["client_secret"],
                        **tokens,
                        "account_email": account,
                    },
                )
                row.enabled, row.writes_enabled = True, bool(config.get("enable_storage"))
                row.last_check = encode(
                    {
                        "revision": row.revision,
                        "status": "succeeded",
                        "created": time.time(),
                        "result": {
                            "label": "LOCAL_ONLY",
                            "scope": " ".join(sorted(expected_scopes)),
                        },
                    }
                )
                _terminal(db, attempt, "succeeded")
                db.commit()
            return _result(cfg, "connected", profile_id)
        except Exception:
            with factory() as db:
                _lock(db)
                attempt = db.get(GoogleDriveOAuthAttempt, attempt_id)
                if attempt and attempt.status == "dispatching":
                    _terminal(db, attempt, "uncertain")
                    db.commit()
            return _result(cfg, "failed", profile_id)

    @app.post("/api/integrations/google-drive/{integration_id}/disconnect")
    def disconnect(integration_id: UUID, body: DisconnectInput, auth: Auth) -> dict[str, Any]:
        if body.revoke_google:
            raise HTTPException(
                422, "Google-Zugriff bitte in den Google-Kontoeinstellungen entfernen"
            )
        with factory() as db:
            _lock(db)
            row = _profile(db, str(integration_id))
            if row.revision != body.expected_revision:
                raise HTTPException(409, "GoogleDrive-Verbindung geändert; neu laden")
            data = credentials(cfg, row)
            row.enabled, row.writes_enabled, row.last_check = False, False, None
            row.revision += 1
            config = json.loads(row.config)
            config.update(
                connected=False,
                account_email="",
                enable_source=False,
                enable_storage=False,
                storage_folder_id="",
            )
            config.pop("oauth_pending_until", None)
            row.config = encode(config)
            _invalidate_attempts(db, row.id)
            _store(
                cfg,
                row,
                {
                    "client_id": data.get("client_id", ""),
                    "client_secret": data.get("client_secret", ""),
                },
            )
            db.commit()
            result = _view(cfg, row)
        return {**result, "google_revoke_status": "not_requested"}


def refresh_credentials(
    db: Session,
    cfg: Settings,
    row: Integration,
    before_send: Callable[[], Any],
    capability: str = "source",
) -> dict[str, Any]:
    """Refresh once under durable intent; never relabel permissions or replay uncertainty."""
    revision = row.revision
    before_send()  # Runtime gates may commit: acquire our intent lock afterwards.
    _lock(db)
    db.refresh(row)
    if row.revision != revision or not ready(cfg, row, capability):
        raise PermissionError("GoogleDrive is not ready")
    data = credentials(cfg, row)
    config = json.loads(row.config)
    if (
        data.get("scope") != " ".join(sorted(configured_scopes(config)))
        or data.get("token_type") != "Bearer"
        or data.get("account_email") != config.get("account_email")
        or not data.get("refresh_token")
    ):
        raise PermissionError("GoogleDrive account or scope changed")
    pending = db.scalar(
        select(GoogleDriveOAuthAttempt).where(
            GoogleDriveOAuthAttempt.integration_id == row.id,
            GoogleDriveOAuthAttempt.operation == "refresh",
            GoogleDriveOAuthAttempt.profile_revision == revision,
            GoogleDriveOAuthAttempt.status == "dispatching",
        )
    )
    if pending and pending.expires > time.time():
        raise PermissionError("GoogleDrive token refresh in progress; no duplicate request")
    if pending:
        pending.status, pending.finished = "uncertain", time.time()
        row.enabled = False
        row.revision += 1
        row.last_check = None
        config.update(connected=False, reauthorization_required=True)
        row.config = encode(config)
        db.commit()
        raise PermissionError("GoogleDrive token refresh requires reconnection without retry")
    if data.get("access_token") and data.get("expires_at", 0) > time.time() + 60:
        before_send()
        return data
    attempt = GoogleDriveOAuthAttempt(
        request_id=new_id(),
        request_digest=digest(row.id + str(revision)),
        operation="refresh",
        integration_id=row.id,
        profile_revision=revision,
        session_hash="",
        status="dispatching",
        expires=time.time() + 90,
    )
    db.add(attempt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise PermissionError("GoogleDrive token refresh already in progress") from None

    def boundary() -> None:
        db.refresh(row)
        if row.revision != revision or not ready(cfg, row, capability):
            raise PermissionError("GoogleDrive authority changed")
        before_send()

    try:
        renewed = google_drive_client.refresh_token(
            data["client_id"],
            data["client_secret"],
            data["refresh_token"],
            configured_scopes(config),
            before_send=boundary,
        )
        boundary()
        _lock(db)
        db.refresh(row)
        if row.revision != revision or not ready(cfg, row, capability):
            raise PermissionError("GoogleDrive authority changed")
        data = {
            **data,
            **renewed,
            "refresh_token": renewed.get("refresh_token") or data["refresh_token"],
        }
        if (
            data.get("scope") != " ".join(sorted(configured_scopes(config)))
            or data.get("token_type") != "Bearer"
        ):
            raise ValueError("Scope changed")
        _store(cfg, row, data)
        attempt.status, attempt.finished = "succeeded", time.time()
        db.commit()
    except Exception:
        db.rollback()
        _lock(db)
        db.refresh(row)
        stored = db.get(GoogleDriveOAuthAttempt, attempt.id)
        if stored:
            stored.status, stored.finished = "uncertain", time.time()
        if row.revision == revision:
            row.enabled = False
            row.revision += 1
            row.last_check = None
            config = json.loads(row.config)
            config.update(connected=False, reauthorization_required=True)
            row.config = encode(config)
        db.commit()
        raise PermissionError(
            "GoogleDrive token renewal failed; reconnect without automatic retry"
        ) from None

    before_send()
    return data


def access_token(
    factory: Any,
    cfg: Settings,
    integration_id: str,
    expected_revision: int,
    capability: str = "source",
    before_send: Callable[[], Any] | None = None,
) -> str:
    """Return only currently authorized tokens; serialized refresh is never blindly replayed."""
    guard = authority_guard(factory, cfg, integration_id, expected_revision, capability)

    def boundary() -> None:
        guard()
        if before_send:
            before_send()

    with factory() as db:
        boundary()
        row = db.get(Integration, integration_id)
        assert row
        value = refresh_credentials(db, cfg, row, boundary, capability)
        boundary()
        return google_drive_client.string(value["access_token"], 8192)
