"""Revisioned routing preferences and deterministic, non-egressing explanations."""

import re
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput
from hub.config import Settings
from hub.db import RoutingSettings
from hub.knowledge_api import Auth
from hub.skill_api import lock


class RoutingOptions(StrictInput):
    strategy: Literal["balanced", "local_first", "cloud_first"] = "balanced"
    complex_research_cloud: bool = True


class RoutingInput(RoutingOptions):
    revision: int = Field(ge=0)


class PreviewInput(StrictInput):
    prompt: str = Field(min_length=1, max_length=12000)
    model_local_only: bool = False
    model_cloud_only: bool = False
    private_context: bool = False
    cloud_allowed: bool = True


def read_options(db: Session) -> dict[str, Any]:
    row = db.get(RoutingSettings, 1)
    if row is None:
        return {"revision": 0, **RoutingOptions().model_dump()}
    return {
        "revision": row.revision,
        "strategy": row.strategy,
        "complex_research_cloud": row.complex_research_cloud,
    }


# A short request is not necessarily simple. Unknown requests use the cloud;
# this allowlist deliberately excludes analysis, files, code and follow-up work.
SIMPLE_MAX_CHARS = 160
SIMPLE_MAX_WORDS = 20


def very_simple_request(prompt: str) -> bool:
    text = prompt.strip().casefold()
    if (len(text) > SIMPLE_MAX_CHARS or len(text.split()) > SIMPLE_MAX_WORDS
            or "\n" in text or "\r" in text):
        return False
    patterns = (
        r"(?:hallo|hi|hello|hey|guten morgen|guten tag|guten abend|"
        r"danke|danke schön|vielen dank|thanks|thank you)[.!?]*",
        r"(?:(?:was ist|wie viel ist|wieviel ist|what is|berechne)\s+)?"
        r"-?\d{1,6}(?:[.,]\d{1,4})?\s*[+*/×÷-]\s*"
        r"-?\d{1,6}(?:[.,]\d{1,4})?[?!.]*",
        r"(?:was ist die hauptstadt von|wie heißt die hauptstadt von|"
        r"what is the capital of)\s+(?:deutschland|germany|frankreich|france|"
        r"italien|italy|spanien|spain|österreich|austria|portugal|"
        r"japan|kanada|canada)[?!.]*",
    )
    return any(re.fullmatch(pattern, text) is not None for pattern in patterns)


def decision(
    prompt: str,
    options: dict[str, Any],
    *,
    classifier: str | None,
    classifier_reason: str = "",
    cloud_enabled: bool,
    cloud_allowed: bool,
    model_local_only: bool,
    private_context: bool,
    model_cloud_only: bool = False,
    private_parts: bool = False,
    builtin: bool = False,
    preview: bool = False,
) -> dict[str, Any]:
    complex_request = bool(
        re.search(
            r"\b(?:komplex\w*|umfassend\w*|gründlich\w*|ausführlich\w*|detailliert\w*|"
            r"complex|comprehensive|in-depth|detailed)\b",
            prompt,
            re.I,
        )
        and re.search(
            r"\b(?:recherche|research|analyse|analysis|analysiere|vergleich\w*|"
            r"bewert\w*|strategie\w*|konzept\w*)\b",
            prompt,
            re.I,
        )
    )
    very_simple = very_simple_request(prompt)
    strategy = options.get("strategy", "balanced")
    chosen = classifier or "local"
    reasons = [
        "Lokale Einordnung des aktuellen Wunsches"
        if classifier
        else "Vorschau ohne Modellaufruf; Freigaben und spätere Einordnung bleiben maßgeblich"
    ]
    if strategy == "cloud_first" and not builtin:
        chosen = "cloud"
        reasons.append("Cloud bevorzugt für generierte Antworten")
    elif strategy == "balanced":
        chosen = "local" if very_simple and classifier != "cloud" else "cloud"
        reasons.append(
            "Kurze, sehr einfache Anfrage aus der lokalen Auswahlliste"
            if chosen == "local"
            else "Auto verwendet Cloud für alle anderen oder unklaren Anfragen"
        )
    elif strategy == "local_first":
        reasons.append("Manuelle lokale Präferenz: die lokale Einordnung entscheidet")
    if model_cloud_only:
        chosen = "cloud"
        reasons = ["Cloud für diesen Lauf ausdrücklich gewählt; Komplexität ist unerheblich"]
    blockers = []
    if model_local_only:
        blockers.append("Nur lokal ist für diesen Lauf gewählt")
    if not cloud_enabled:
        blockers.append("Cloud ist auf dem Server deaktiviert")
    if not cloud_allowed:
        blockers.append("Cloud ist für diesen Gesprächskontext nicht freigegeben")
    if private_context or private_parts:
        blockers.append("Der Antwortkontext enthält lokal geschützte Inhalte")
    if builtin and not model_cloud_only:
        blockers.append("Diese Antwort ist eine lokale Systemauskunft")
    return {
        "policy_revision": options.get("revision", 0),
        "strategy": strategy,
        "classifier_model_class": classifier,
        "classifier_reason": classifier_reason,
        "policy_model_class": chosen,
        "effective_model_class": (
            ("blocked" if model_cloud_only else "local") if blockers else chosen
        ),
        "requested_mode": "cloud" if model_cloud_only else "local" if model_local_only else "auto",
        "complexity": "complex" if complex_request else "simple" if very_simple else "standard",
        "reasons": reasons,
        "blockers": blockers,
        "preview": preview,
    }


def install_routing_settings_api(
    app: FastAPI, cfg: Settings, factory: sessionmaker[Session]
) -> None:
    @app.get("/api/routing-settings")
    def get(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return {**read_options(db), "cloudEnabled": cfg.cloud_enabled}

    @app.put("/api/routing-settings")
    def put(body: RoutingInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            current = read_options(db)
            if current["revision"] != body.revision:
                raise HTTPException(409, "Routing inzwischen geändert; neu laden")
            row = db.get(RoutingSettings, 1)
            if row is None:
                row = RoutingSettings(id=1)
                db.add(row)
            row.strategy = body.strategy
            row.complex_research_cloud = body.complex_research_cloud
            row.revision = body.revision + 1
            db.commit()
            return {**read_options(db), "cloudEnabled": cfg.cloud_enabled}

    @app.post("/api/routing-settings/preview")
    def preview(body: PreviewInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            options = read_options(db)
        return decision(
            body.prompt,
            options,
            classifier=None,
            cloud_enabled=cfg.cloud_enabled,
            cloud_allowed=body.cloud_allowed,
            model_local_only=body.model_local_only,
            model_cloud_only=body.model_cloud_only,
            private_context=body.private_context,
            preview=True,
        )
