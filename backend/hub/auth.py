import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request

from hub.db import LoginSession


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
