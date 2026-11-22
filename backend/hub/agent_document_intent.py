"""Pure document-content/reference recognition; unknown wording uses semantic intent."""

import re

_CONTENT = re.compile(
    r"zusammenfass|\bfasse\b|\binhalt\b|\bocr\b|\blesen\b|\blies\b|"
    r"\bzeige\b|\benthält\b|\bsteht\b|summari|\bread\b|\bcontent\b",
    re.I,
)
_OTHER = re.compile(
    r"\b(?:suche|such|finde|filtere|durchsuche|search|find|filter|"
    r"lösche|lösch|entferne|ändere|änder|benenne|umbenennen|speichere|"
    r"sende|verschicke|exportiere|download|herunterladen|hochladen|"
    r"delete|remove|rename|update|write|send|export|upload)\b",
    re.I,
)
_ORDINALS = {
    "erst": 1,
    "zweit": 2,
    "dritt": 3,
    "viert": 4,
    "fünft": 5,
    "sechst": 6,
    "siebt": 7,
    "acht": 8,
    "neunt": 9,
    "zehnt": 10,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
}


def selection(goal: str) -> tuple[str, int] | None:
    """Interpret resource references only; never decide that the goal is complete."""
    # A bound prior-search noun phrase is a reference, not a request to search again.
    action_goal = re.sub(
        r"\b(?:aus|von|in)\s+(?:der|deiner|unserer|meiner|dieser)\s+"
        r"(?:letzten|vorherigen|bisherigen)\s+(?:suche|abfrage)\b|"
        r"\bfrom\s+(?:the|your|our|my)\s+(?:last|previous)\s+search\b",
        "",
        goal,
        flags=re.I,
    )
    if not _CONTENT.search(goal) or _OTHER.search(action_goal):
        return None
    if re.search(
        r"\b(?:nur|mindestens|höchstens|where|filtered)\b|"
        r"\b(?:von|seit|vor|nach|mit|ohne)\s+\d",
        goal,
        re.I,
    ):
        return None
    ids = re.findall(
        r"\b(?:dokument|document)(?:[-\s]*(?:id|nr\.?|nummer|number))?"
        r"\s*[:#]?\s*([1-9][0-9]*)\b",
        goal,
        re.I,
    )
    # Asking to *name* an ID is not an explicit ID selection.
    if ids:
        return ("id", int(ids[0])) if len(set(ids)) == 1 else None
    if re.search(r"\bdokument[-\s]*(?:id|nummer)\s*[:#]?\s*0\b", goal, re.I):
        return None
    if re.search(
        r"\bdie\s+(?:ersten|zweiten|dritten|vierten|fünften|sechsten|siebten|achten|neunten|zehnten)"
        r"\s+(?:(?:gefunden|angezeigt)(?:en)?\s+)?treffer\b",
        goal,
        re.I,
    ):
        return None
    ordinals = []
    for stem, number in _ORDINALS.items():
        pattern = (
            rf"\b{stem}(?:e|en|er|es|em)?\s+"
            r"(?:(?:gefunden|angezeigt|beobachtet|found|listed)(?:e|en|er|es|em)?\s+)?"
            r"(?:dokument(?:s)?|document|treffer(?:s)?|result|hit)\b"
        )
        # A singular partitive points into the prior result set: "im ersten
        # dieser Dokumente" still selects one document, unlike "die ersten".
        partitive = (
            rf"\b(?:im|vom|am|zum|des|dem|den|das)\s+{stem}(?:e|en|er|es|em)?\s+"
            r"(?:dieser|der)\s+(?:(?:gefunden|angezeigt|beobachtet)en\s+)?"
            r"(?:dokumente|treffer)\b"
        )
        if re.search(pattern, goal, re.I) or re.search(partitive, goal, re.I):
            ordinals.append(number)
    ordinals.extend(
        int(n)
        for n in re.findall(
            r"\b([1-9][0-9]*)\.\s+(?:(?:gefunden|angezeigt|beobachtet)(?:e|en|er|es|em)?\s+)?"
            r"(?:dokument(?:s)?|treffer(?:s)?)\b",
            goal,
            re.I,
        )
    )
    return ("ordinal", ordinals[0]) if len(set(ordinals)) == 1 else None



def content_requested(goal: str) -> bool:
    return bool(_CONTENT.search(goal))


_DEICTIC = re.compile(
    r"\b(?:darin|daraus|hierin|hieraus)\b|\b(?:in|inside|from)\s+it\b", re.I,
)


def bound_content_reference(goal: str, *, semantic_followup: bool = False) -> bool:
    """A singular resource reference, never a question template or a new search."""
    if _OTHER.search(goal):
        return False
    return bool(semantic_followup or (_CONTENT.search(goal) and _DEICTIC.search(goal)))
