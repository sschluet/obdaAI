"""Local lexical routing to current authorized interfaces; never contacts a target."""

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from hub.agent_models import AgentPolicy
from hub.agent_tools import Rules
from hub.config import Settings
from hub.integration_api import approved, freeze_bindings
from hub.integrations import Integration

MAIL = re.compile(r"\b(mail(?:s|box)?|e[ -]?mails?|postfach|posteingang|inbox|emails?)\b")
EXPLANATION = re.compile(
    r"^\s*(?:erkl[aä]r\w*|explain|[uü]bersetz\w*|translate|definiere|define|"
    r"was (?:ist|bedeutet)|what is|wie (?:richte|installiere|konfiguriere|funktioniert)|"
    r"how (?:do i|does|to))\b"
)
SEND = re.compile(r"\b(sende\w*|schick\w*|versend\w*|send|forward|weiterleit\w*)\b")
EXISTING_MAIL = re.compile(
    r"\b(lies|lese\w*|zeige\w*|such\w*|finde\w*|search|read|list|reply|antwort\w*|"
    r"beantwort\w*|weiterleit\w*|forward|thread|zusammenfass\w*|postfach|posteingang|"
    r"inbox|erhalten\w*|eingegang\w*|vorhanden\w*)\b"
)
PUBLIC_RESEARCH = re.compile(
    r"\b(neuigkeiten|news|dokumentation|documentation|im internet|im web|public research|"
    r"recherchier\w*|research)\b"
)
FILE_CREATION = re.compile(
    r"(?s)(?=.*\b(erstell\w*|erzeug\w*|schreib\w*|verfass\w*|create|generate|write)\b)"
    r"(?=.*\b(word|excel|powerpoint|pdf|pr[aä]sentation|spreadsheet|docx|pptx|xlsx)\b)"
)
ALIASES = {
    "home_assistant": re.compile(
        r"\b(home ?assistant|ha|smarthome|smart home|hausautomation|licht|heizung|sensor\w*)\b"
    ),
    "paperless": re.compile(
        r"\b(paperless|dokument\w*|documents?|rechnungen?|invoices?|archiv\w*)\b"
    ),
    "unifi": re.compile(r"\b(unifi|wlan|wifi|wi-fi|netzwerk|network|router|access ?point\w*)\b"),
    "ssh": re.compile(r"\b(ssh|mac ?mini|server|linux|terminal|dateisystem|filesystem)\b"),
}


def relevant(goal: str, row: Integration, rules: Rules) -> bool:
    """Known interface vocabulary only; remote descriptions never become instructions."""
    text = goal.casefold()
    if EXPLANATION.search(text):
        return False
    if PUBLIC_RESEARCH.search(text) and not re.search(r"\b(mein\w*|unser\w*|my|our)\b", text):
        return False
    if (
        FILE_CREATION.search(text)
        and not MAIL.search(text)
        and not re.search(
            r"\b(paperless|archiv\w*)\b|"
            r"\b(mein\w*|unser\w*|my|our)\s+(?:vorhanden\w*\s+)?"
            r"(rechnungen|dokumente\w*|documents?|invoices?)\b",
            text,
        )
    ):
        return False
    if row.kind == "smtp":
        return bool((MAIL.search(text) or re.search(r"\bsmtp\b", text)) and SEND.search(text))
    if row.kind == "gmail":
        if SEND.search(text) and not EXISTING_MAIL.search(text):
            return False
        return bool(MAIL.search(text) or named_mail_interface(goal, row))
    if row.kind == "mcp":
        names = set(rules.mcp_read_tools)
        mail_interface = bool(
            names & {"list_emails", "read_email", "search_emails", "daily_digest", "get_thread"}
        )
        if mail_interface and SEND.search(text) and not EXISTING_MAIL.search(text):
            return False
        if mail_interface and (MAIL.search(text) or named_mail_interface(goal, row)):
            return True
        if any(
            name.replace("_", " ").casefold() in text or name.casefold() in text for name in names
        ):
            return True
    aliases = ALIASES.get(row.kind)
    if aliases and aliases.search(text):
        return True
    if (
        row.kind == "paperless"
        and re.search(r"\b(\w*unterlagen|vertr[aä]g\w*|belege[n]?)\b", text)
        and re.search(
            r"\b(mein\w*|unser\w*|my|our|such\w*|finde\w*|zeig\w*|lies|"
            r"liste\w*|steht|enthalt\w*|letzten)\b",
            text,
        )
    ):
        return True
    name = row.name.strip().casefold()
    return len(name) >= 3 and name in text


def mail_interface(row: Integration, rules: Rules) -> bool:
    return (
        row.kind in {"gmail", "smtp"}
        or row.kind == "mcp"
        and bool(
            set(rules.mcp_read_tools)
            & {"list_emails", "read_email", "search_emails", "daily_digest", "get_thread"}
        )
    )


def named_mail_interface(goal: str, row: Integration) -> bool:
    text = goal.casefold()
    name = row.name.strip().casefold()
    return bool(
        len(name) >= 3
        and name in text
        or row.kind == "gmail"
        and re.search(r"\bgmail\b", text)
        or "proton" in name
        and re.search(r"\bproton(?:mail)?\b", text)
    )


def usable(kind: str, rules: Rules) -> bool:
    return bool(
        rules.enabled
        and (
            kind == "mcp"
            and (rules.mcp or rules.mcp_read_tools)
            or kind == "gmail"
            and rules.gmail_read
            or kind == "smtp"
            and rules.mail_recipients
            or kind == "ssh"
            and (rules.shell or rules.file_read_roots)
            or kind in {"home_assistant", "paperless", "unifi"}
            and (
                rules.http_prefixes
                and rules.http_methods
                or kind == "home_assistant"
                and rules.ha_websocket_prefixes
            )
        )
    )


def matching_integrations(
    db: Session,
    cfg: Settings,
    selected: dict[str, Any],
    goal: str,
    *,
    conversation_id: str | None = None,
) -> list[str]:
    candidates = []
    for item in selected["bindings"]:
        row = db.get(Integration, item["id"])
        policy = db.get(AgentPolicy, item["id"])
        if (
            not row
            or not policy
            or policy.profile_revision != row.revision
            or not approved(cfg, row)
        ):
            continue
        rules = Rules.model_validate_json(policy.rules)
        if not usable(row.kind, rules):
            continue
        if row.kind == "gmail":
            from hub.gmail_setup import read_ready

            if not read_ready(cfg, row):
                continue
        config = json.loads(row.config)
        if config.get("auth") != "none" and not row.encrypted_secret:
            continue
        candidates.append((row, rules))
    named = {
        row.id
        for row, rules in candidates
        if mail_interface(row, rules) and named_mail_interface(goal, row)
    }
    matches = [
        row.id
        for row, rules in candidates
        if relevant(goal, row, rules)
        and (not named or not mail_interface(row, rules) or row.id in named)
    ]
    if (
        not matches
        and conversation_id
        and not EXPLANATION.search(goal.casefold())
        and not PUBLIC_RESEARCH.search(goal.casefold())
        and not FILE_CREATION.search(goal.casefold())
        and re.search(
            r"\b(davon|darin|darauf|dazu|diese[rmns]?|vorhin|genannten|"
            r"aufgelisteten|geantwortet|beantwortet)\b",
            goal.casefold(),
        )
    ):
        from hub.agent_read_references import previous_profile_ids

        profiles = {row.id: (row, rules, json.loads(row.config)) for row, rules in candidates}
        matches = list(previous_profile_ids(db, conversation_id, profiles))
    return sorted(matches)


def route_integrations(
    db: Session, cfg: Settings, conversation_id: str, goal: str
) -> dict[str, Any]:
    matches = matching_integrations(
        db,
        cfg,
        freeze_bindings(db, "conversation", conversation_id),
        goal,
        conversation_id=conversation_id,
    )
    return {"route": "agent" if matches else "chat", "integration_ids": matches}
