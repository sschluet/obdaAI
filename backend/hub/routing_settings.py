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
    strategy = options.get("strategy", "balanced")
    chosen = classifier or "local"
    reasons = [
        "Lokale Einordnung des aktuellen Wunsches"
        if classifier
        else "Vorschau ohne Modellaufruf; die spätere Einordnung kann abweichen"
    ]
    if strategy == "cloud_first" and not builtin:
        chosen = "cloud"
        reasons.append("Cloud bevorzugt für generierte Antworten")
    elif strategy == "balanced" and options.get("complex_research_cloud", True) and complex_request:
        chosen = "cloud"
        reasons.append(
            "Komplexe Recherche oder Analyse: Cloud für höhere Antwortqualität bevorzugt"
        )
    elif strategy == "local_first":
        reasons.append("Lokale Einordnung entscheidet; kein automatischer Komplexitätsaufschlag")
    else:
        reasons.append("Ausgewogene Auswahl anhand der lokalen Einordnung")
    blockers = []
    if model_local_only:
        blockers.append("Nur lokal ist für diesen Lauf gewählt")
    if not cloud_enabled:
        blockers.append("Cloud ist auf dem Server deaktiviert")
    if not cloud_allowed:
        blockers.append("Cloud ist für diesen Gesprächskontext nicht freigegeben")
    if private_context or private_parts:
        blockers.append("Der Antwortkontext enthält lokal geschützte Inhalte")
    if builtin:
        blockers.append("Diese Antwort ist eine lokale Systemauskunft")
    return {
        "policy_revision": options.get("revision", 0),
        "strategy": strategy,
        "classifier_model_class": classifier,
        "classifier_reason": classifier_reason,
        "policy_model_class": chosen,
        "effective_model_class": "local" if blockers else chosen,
        "complexity": "complex" if complex_request else "simple",
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
            private_context=body.private_context,
            preview=True,
        )
