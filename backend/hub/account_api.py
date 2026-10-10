import hmac
import time
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from hub.auth import (
    consume_auth_attempt,
    locked_credential,
    password_hash,
    require_session,
    verify_password,
)
from hub.config import Settings
from hub.db import LoginSession


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(min_length=1, max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=256)
    confirm_password: SecretStr = Field(min_length=12, max_length=256)


def install_account_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.post("/api/account/password")
    def change_password(
        body: PasswordChange,
        session: Annotated[LoginSession, Depends(require_session)],
        response: Response,
    ) -> dict[str, bool]:
        current = body.current_password.get_secret_value()
        new = body.new_password.get_secret_value()
        confirmed = body.confirm_password.get_secret_value()
        if not hmac.compare_digest(new.encode(), confirmed.encode()):
            raise HTTPException(422, "Die neuen Passwörter stimmen nicht überein")
        if hmac.compare_digest(current.encode(), new.encode()):
            raise HTTPException(422, "Bitte ein anderes neues Passwort wählen")
        now = time.time()
        consume_auth_attempt(factory, 2, now)
        with factory() as db:
            credential = locked_credential(db)
            active = db.get(LoginSession, session.token_hash)
            if active is None or active.expires <= time.time():
                raise HTTPException(401, "Anmeldung erforderlich")
            stored = credential.password_hash or cfg.password_hash
            if not stored or not verify_password(current, stored):
                raise HTTPException(401, "Aktuelles Passwort ist nicht korrekt")
            credential.password_hash = password_hash(new)
            credential.revision += 1
            credential.changed = time.time()
            db.execute(delete(LoginSession))
            db.commit()
        response.delete_cookie("hub_session", secure=cfg.secure_cookie, samesite="strict")
        return {"changed": True, "reauthenticate": True}
