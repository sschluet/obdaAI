import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request
from sqlalchemy import case, update
from sqlalchemy.orm import Session, sessionmaker

from hub.db import AccountCredential, LoginSession, LoginThrottle


def consume_auth_attempt(factory: sessionmaker[Session], bucket: int, now: float) -> None:
    """Persist attempts before verification, including unsuccessful requests."""
    with factory() as db:
        count = db.scalar(
            update(LoginThrottle)
            .where(LoginThrottle.id == bucket)
            .values(
                attempts=case(
                    (LoginThrottle.window < now - 60, 1), else_=LoginThrottle.attempts + 1
                ),
                window=case((LoginThrottle.window < now - 60, now), else_=LoginThrottle.window),
            )
            .returning(LoginThrottle.attempts)
        )
        db.commit()
    if count is None or count > 5:
        raise HTTPException(429, "Bitte eine Minute warten")


def locked_credential(db: Session) -> AccountCredential:
    """One write lock serializes credential checks and session creation/revocation.

    UPDATE also provides serialization on SQLite, where SELECT FOR UPDATE does
    not lock. All credential-changing and login transactions use this lock.
    """
    found = db.scalar(
        update(AccountCredential)
        .where(AccountCredential.id == 1)
        .values(revision=AccountCredential.revision)
        .returning(AccountCredential.id)
    )
    if found is None:
        raise HTTPException(503, "Anmeldung erfordert die aktuelle Datenbankmigration")
    credential = db.get(AccountCredential, 1)
    assert credential is not None
    return credential


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return salt + ":" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split(":", 1)
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def require_session(request: Request) -> LoginSession:
    token = request.cookies.get("hub_session", "")
    with request.app.state.sessions() as db:
        session: LoginSession | None = db.get(LoginSession, token_hash(token))
        if session is None or session.expires <= time.time():
            raise HTTPException(401, "Anmeldung erforderlich")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            check_origin(request)
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session.csrf):
                raise HTTPException(403, "CSRF-Prüfung fehlgeschlagen")
        return session


def check_origin(request: Request) -> None:
    if request.headers.get("Origin") != request.app.state.settings.origin:
        raise HTTPException(403, "Nicht erlaubter Origin")
