"""Small physical commands are parsed from the direct user's goal, never source text."""

import re
from typing import Any


def pages(goal: str) -> list[dict[str, int]] | None:
    text = goal.casefold()
    ordered = re.findall(r"(?:zuerst|danach|anschließend)\s+(?:original)?seite\s+(\d{1,3})", text)
    if len(ordered) >= 2:
        numbers = [int(n) for n in ordered]
    else:
        match = re.search(
            r"\b(?:mit|reihenfolge|auswahl)\s+(?:den\s+)?seiten?\s*:?\s*(\d{1,3}(?:\s*(?:,|und|bis|-)\s*\d{1,3})*)",
            text,
        )
        if not match:
            return None
        numbers = []
        for part in re.split(r"\s*(?:,|und)\s*", match[1]):
            span = re.fullmatch(r"(\d{1,3})\s*(?:bis|-)\s*(\d{1,3})", part)
            if span:
                first, last = map(int, span.groups())
                numbers.extend(
                    range(first, last + (1 if first <= last else -1), 1 if first <= last else -1)
                )
            else:
                numbers.append(int(part))
    if not numbers or len(numbers) > 100 or any(not 1 <= n <= 1000 for n in numbers):
        raise ValueError("PDF-Seitenauftrag überschreitet die Auswahlgrenzen")
    result = [{"source": 0, "page": n, "rotation": 0} for n in numbers]
    rotations = list(
        re.finditer(
            r"drehe\s+(?:die\s+)?(?:(erste|zweite|dritte)\s+ausgabeseite|ausgabeseite\s+(\d{1,3})|(?:original)?seite\s+(\d{1,3}))\s+um\s+(90|180|270)\s*(?:grad|°)(\s+gegen\s+den\s+uhrzeigersinn)?",
            text,
        )
    )
    if re.search(r"\b(?:drehe|rotation|rotiere)\b", text) and not rotations:
        return None
    for match in rotations:
        ordinal, index, page, angle, reverse = match.groups()
        turn = (360 - int(angle)) % 360 if reverse else int(angle)
        if ordinal or index:
            at = {"erste": 0, "zweite": 1, "dritte": 2}[ordinal] if ordinal else int(index) - 1
            if not 0 <= at < len(result):
                raise ValueError("Ausgabeseite fehlt im Auftrag")
            result[at]["rotation"] = turn
        else:
            selected = [r for r in result if r["page"] == int(page)]
            if not selected:
                raise ValueError("Zu drehende Originalseite ist nicht ausgewählt")
            for row in selected:
                row["rotation"] = turn
    return result


def image(goal: str) -> dict[str, Any] | None:
    text = goal.casefold()
    size = re.search(r"auf\s+(\d{2,4})\s*(?:mal|x|×)\s*(\d{2,4})\s*pixel", text)
    if not size:
        return None
    width, height = map(int, size.groups())
    crop = None
    if re.search(r"\brechte\s+hälfte\b", text):
        crop = [0.5, 0, 1, 1]
    elif re.search(r"\blinke\s+hälfte\b", text):
        crop = [0, 0, 0.5, 1]
    else:
        values = []
        for name in (r"linker\s+rand", r"oben", r"rechts", r"unten"):
            match = re.search(name + r"\s+(\d{1,3})\s*prozent", text)
            if not match:
                return None
            values.append(int(match[1]) / 100)
        crop = values
    if re.search(r"\b(?:beschrifte|caption)\b", text):
        return None
    return {
        "tiles": [{"source": 0, "crop": crop, "caption": ""}],
        "columns": 1,
        "tile_width": width,
        "tile_height": height,
        "format": "jpeg" if re.search(r"\b(?:jpeg|jpg)[- ]datei\b", text) else "png",
    }


def split_after(goal: str, count: int) -> list[int] | None:
    """Only explicit direct-user boundaries; no inferred document semantics."""
    text = goal.casefold()
    if re.search(r"\b(?:teile|aufteilen|split|trenne)\b", text) and re.search(
        r"(?:jede\s+(?:ausgabe)?seite|einzel[- ]?pdfs?)", text
    ):
        if not 2 <= count <= 20:
            raise ValueError("Zwei bis zwanzig Einzel-PDFs je Auftrag")
        return list(range(1, count))
    match = re.search(
        r"trenne\s+nach\s+(?:den\s+)?ausgabeseiten?\s+"
        r"(\d{1,3}(?:\s*(?:,|und)\s*\d{1,3})*)",
        text,
    )
    if match:
        return [int(n) for n in re.split(r"\s*(?:,|und)\s*", match[1])]
    return None
