"""Detect misplaced tool-confirmation prose, without parsing or authorizing a call."""

import re

from hub.agent_tools import SCHEMAS

_TOOL = re.compile(
    r"(?<![\w.])(?:" + "|".join(re.escape(name) for name in sorted(SCHEMAS, key=len, reverse=True))
    + r")(?![\w.]|://)",
    re.IGNORECASE,
)
_CONFIRM = re.compile(
    r"\b(?:bitte\s+(?:bestätig\w*|freigeben)|bestätig\w*\s+(?:bitte|sie)|"
    r"please\s+confirm|confirm\s+(?:the|this|following)|"
    r"(?:may|can)\s+i\s+(?:execute|run|call|send)|darf\s+ich)\b",
    re.IGNORECASE,
)
_PARAMETER = re.compile(
    r"\b(?:path|arguments|parameters|expected)\s*=|"
    r'''["'](?:path|arguments|parameters|expected)["']\s*:''',
    re.IGNORECASE,
)
_CHOICE = re.compile(
    r"\b(?:bestätig\w*|confirm)\s*(?:sie\s*|bitte\s*)?[,.:]?\s*"
    r"(?:welch\w*|which|what|whether|ob)\b",
    re.IGNORECASE,
)


def tool_confirmation(message: str) -> bool:
    """Only identify confirmation prose containing a named tool and labeled parameters.

    A match requests format repair, never execution or inferred permission. No
    parameters are extracted, logged, interpreted or returned.
    """
    if not isinstance(message, str) or not 1 <= len(message) <= 12000:
        return False
    return bool(_CONFIRM.search(message) and _TOOL.search(message)
                and _PARAMETER.search(message) and not _CHOICE.search(message))

_EXECUTION = re.compile(
    r"\b(?:ausführen|ausgeführt|durchführen|durchgeführt|starten|gestartet|"
    r"installieren|installiert|execute|executed|execution|run|perform|performed|"
    r"install|installed|start|started|proceed)\b",
    re.IGNORECASE,
)
_ESSENTIAL_CHOICE = re.compile(
    r"\b(?:welch\w*|which|what|where|how|wo|wie|oder|or|alternativ\w*|"
    r"parameter\w*|schwellwert\w*|threshold\w*|sollwert\w*|zielzustand\w*|"
    r"fehlt|fehlen|missing|specify|angeben|festlegen|auswählen|wählen|"
    r"gewünschte\w*|desired)\b",
    re.IGNORECASE,
)


def execution_confirmation(message: str) -> bool:
    """Recognize redundant execution approval, not missing operational choices.

    The caller must separately bind this signal to a certain administrative user
    request. It grants no authority and never supplies missing execution details.
    """
    if not isinstance(message, str) or not 1 <= len(message) <= 12000:
        return False
    return bool(_CONFIRM.search(message) and _EXECUTION.search(message)
                and not _ESSENTIAL_CHOICE.search(message))
