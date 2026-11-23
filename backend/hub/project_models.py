"""One project model preference; model choice never grants data or tool access."""

import json
import re
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from hub.config import Settings
from hub.db import Project, ProviderConfig
from hub.provider_settings import local_endpoints

CLOUD_BLOCKED = "Cloud gewählt; Projektinhalte sind noch nicht für externe Modelle freigegeben."


class ProjectModelError(ValueError):
    pass


def policy(value: str | dict[str, Any]) -> dict[str, str]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        raise ProjectModelError("Projektmodell ist ungültig; Auswahl erneut speichern.") from None
    if parsed == {}:
        return {}
    if not isinstance(parsed, dict) or set(parsed) != {"provider_id", "model"}:
        raise ProjectModelError("Auto oder einen konfigurierten Anbieter mit Modell wählen.")
    identifier, model = parsed["provider_id"], parsed["model"]
    if (type(identifier) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,36}", identifier)
            or type(model) is not str or not 1 <= len(model) <= 240
            or any(ord(c) < 32 or ord(c) == 127 for c in model)):
        raise ProjectModelError("Projektmodell ist ungültig; Auswahl erneut speichern.")
    return {"provider_id": identifier, "model": model}


def configured(db: Session, cfg: Settings, choice: dict[str, str]) -> ProviderConfig:
    row = db.get(ProviderConfig, choice["provider_id"], populate_existing=True)
    if not row or not row.enabled:
        raise ProjectModelError("Gewählter Modellanbieter fehlt oder ist deaktiviert.")
    try:
        data = json.loads(row.config)
        if data["model"] != choice["model"]:
            raise ProjectModelError("Gewähltes Modell wurde geändert; Projektmodell erneut wählen.")
        if "text" not in data["capabilities"]:
            raise ProjectModelError("Gewähltes Modell unterstützt keine Textantworten.")
        if row.kind == "local":
            if "LOCAL_ONLY" not in data["allowed_labels"]:
                raise ProjectModelError("Das lokale Projektmodell erlaubt keine privaten Inhalte.")
            if "structured" not in data["capabilities"]:
                raise ProjectModelError("Das lokale Projektmodell benötigt strukturierte Ausgabe.")
            if data["base_url"] not in local_endpoints(cfg):
                raise ProjectModelError("Gewählter Modellserver ist nicht freigegeben.")
        elif row.kind not in {"openrouter", "openai", "anthropic"}:
            raise ProjectModelError("Dieser Modellanbieter wird nicht unterstützt.")
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ProjectModelError("Modellkonfiguration ist ungültig; Anbieter prüfen.") from None
    return row


def status(db: Session, cfg: Settings, project: Project) -> dict[str, Any]:
    try:
        selected = policy(project.model_policy)
        if not selected:
            return {"available": True, "reason": "Automatische Modellauswahl"}
        row = configured(db, cfg, selected)
        if row.kind != "local":
            return {"available": False, "reason": CLOUD_BLOCKED}
        return {"available": True, "reason": "Gewähltes lokales Projektmodell"}
    except ProjectModelError as error:
        return {"available": False, "reason": str(error)}


def save_policy(db: Session, cfg: Settings, value: dict[str, Any]) -> str:
    selected = policy(value)
    if selected:
        configured(db, cfg, selected)
    # Saving a cloud preference is deliberately distinct from authorizing data egress.
    return json.dumps(selected, sort_keys=True, separators=(",", ":"))


def freeze(db: Session, cfg: Settings, project_id: str | None) -> dict[str, Any] | None:
    if not project_id:
        return None
    project = db.get(Project, project_id, populate_existing=True)
    if not project or project.archived:
        raise ProjectModelError("Projekt fehlt oder ist archiviert.")
    selected = policy(project.model_policy)
    frozen: dict[str, Any] = {"project_id": project.id, "project_revision": project.revision,
                              "policy": selected}
    if selected:
        row = configured(db, cfg, selected)
        if row.kind != "local":
            raise ProjectModelError(CLOUD_BLOCKED)
        frozen.update(provider_id=row.id, provider_revision=row.revision, kind=row.kind,
                      model=selected["model"])
    return frozen


def check(db: Session, cfg: Settings, frozen: dict[str, Any] | None) -> None:
    if frozen and freeze(db, cfg, frozen["project_id"]) != frozen:
        raise ProjectModelError("Projektmodell oder Anbieter wurde während des Auftrags geändert.")


class ProviderArguments(TypedDict, total=False):
    provider_id: str
    model: str


def provider_arguments(frozen: dict[str, Any] | None) -> ProviderArguments:
    return ({"provider_id": frozen["provider_id"], "model": frozen["model"]}
            if frozen and frozen.get("policy") else {})


def selection_snapshot(db: Session, project_id: str | None) -> dict[str, Any] | None:
    """Saved tasks inherit current policy at each trigger, without rewriting their spec."""
    if not project_id:
        return None
    project = db.get(Project, project_id, populate_existing=True)
    if not project or project.archived:
        raise ProjectModelError("Projekt fehlt oder ist archiviert.")
    selected = policy(project.model_policy)
    return ({"project_id": project.id, "project_revision": project.revision, "policy": selected}
            if selected else None)
