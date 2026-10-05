"""Concrete read-only HA maintenance plan; metadata never substitutes for recovery."""

import re
import time
from typing import Any

from hub.config import Settings
from hub.ha_backups import inspect as backup_inspect
from hub.home_assistant import inspect as state_inspect


def plan(state: dict[str, Any], backup: dict[str, Any]) -> dict[str, Any]:
    issues = []
    if backup.get("supervisor_healthy") is not True:
        issues.append("Supervisor nicht als gesund bestätigt")
    if backup.get("supervisor_supported") is not True:
        issues.append("Unterstützte Installation nicht bestätigt")
    if backup.get("backup_state") != "idle":
        issues.append("Sicherungsdienst nicht als bereit bestätigt")
    if backup.get("agent_error_count", 0):
        issues.append("Fehler bei Sicherungsspeicherzugängen gemeldet")
    copies = [
        b
        for b in backup.get("backups", [])
        if b.get("homeassistant_included") is True
        and b.get("database_included") is True
        and b.get("failure_count") == 0
        and any(c.get("size", 0) > 0 for c in b.get("copies", []))
    ]
    newest = max(copies, key=lambda b: b.get("created") or 0, default=None)
    if not newest:
        issues.append("Keine vollständige Sicherung aus Metadaten erkennbar")
    # These are hard blockers: API metadata or a UI checkbox cannot satisfy them.
    issues.extend(
        [
            "Archivintegrität nicht geprüft",
            "Wiederherstellungsschlüssel nicht geprüft",
            "Erfolgreicher Wiederherstellungsweg nicht nachgewiesen",
        ]
    )
    candidates = []
    for update in state.get("updates", []):
        if update["state"] == "off":
            continue
        old, new = update.get("installed_version"), update.get("latest_version")
        old_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", old or "")
        new_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", new or "")
        same_release = bool(
            old_match
            and new_match
            and old_match.group(1, 2) == new_match.group(1, 2)
            and int(new_match.group(3)) > int(old_match.group(3))
        )
        candidates.append(
            {
                **update,
                "version_change": "patch_candidate" if same_release else "separate_review",
                "execution_allowed": False,
                "reason": (
                    "Konkrete Komponenten-/Versionsfreigabe und "
                    "geprüfte Wiederherstellung erforderlich"
                )
                if same_release
                else "Größerer, unbekannter oder nicht verfügbarer Versionswechsel separat prüfen",
            }
        )
    return {
        "label": "LOCAL_ONLY",
        "checked_at": time.time(),
        "profile": "analyze_only",
        "writes_enabled": False,
        "restore_verified": False,
        "blockers": issues,
        "latest_backup_metadata": newest,
        "updates": candidates,
        "state": state,
        "backup": backup,
        "steps": [
            "Bestand und Updatezustand lesen",
            "Konkrete Komponente und Zielversion prüfen",
            "Sicherungsarchiv und Schlüssel prüfen",
            "Wiederherstellungsweg nachweisen",
            "Aktionsgebundene Freigabe im Wartungsfenster einholen",
            "Erst danach Änderung einzeln ausführen und Funktion prüfen",
        ],
        "executed_changes": [],
    }


def inspect(cfg: Settings) -> dict[str, Any]:
    return plan(state_inspect(cfg), backup_inspect(cfg))
