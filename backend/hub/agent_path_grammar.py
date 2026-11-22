"""Positive regular languages for HA read paths, compatible with local grammars.

Generation constraints are hints plus a first filter. The final policy validator
still independently classifies HA webhooks as effects and blocks read-only runs.
"""

import re
import string
from collections.abc import Sequence

_ALPHABET = string.ascii_letters + string.digits + "_.~/-"
_TAIL = "[A-Za-z0-9_.~/-]*"
_BLOCKED = "/api/webhook"


def _case_character(value: str) -> str:
    return "[" + value.lower() + value.upper() + "]" if value.isalpha() else re.escape(value)


def _different_character(value: str) -> str:
    denied = {value.lower(), value.upper()}
    groups = []
    for alphabet in (string.ascii_uppercase, string.ascii_lowercase, string.digits):
        runs: list[str] = []
        for character in alphabet:
            if character in denied:
                if runs:
                    groups.append(runs[0] + "-" + runs[-1] if len(runs) > 2 else "".join(runs))
                    runs = []
            else:
                runs.append(character)
        if runs:
            groups.append(runs[0] + "-" + runs[-1] if len(runs) > 2 else "".join(runs))
    groups.extend(re.escape(c) for c in "_.~/-" if c not in denied)
    return "[" + "".join(groups) + "]"


def ha_read_path_pattern(prefixes: Sequence[str]) -> str | None:
    """Intersect configured prefixes with non-webhook paths, without lookaround.

    None means no read path exists; callers omit that tool alternative. The
    construction enumerates only where a forbidden word first differs, plus
    strictly shorter paths and longer non-directory suffixes. It never uses a
    negative lookahead or the unsupported JSON Schema ``not`` keyword.
    """
    alternatives = []
    for prefix in prefixes:
        if (
            not prefix.startswith("/")
            or not prefix.endswith("/")
            or any(character not in _ALPHABET for character in prefix)
        ):
            raise ValueError("Expected a validated API directory prefix")
        folded = prefix.casefold()
        if folded.startswith(_BLOCKED + "/"):
            continue
        if not _BLOCKED.startswith(folded):
            alternatives.append(re.escape(prefix) + _TAIL)
            continue
        remainder = _BLOCKED[len(prefix) :]
        matched = ""
        for character in remainder:
            alternatives.append(re.escape(prefix) + matched)  # End before the blocked path.
            alternatives.append(
                re.escape(prefix) + matched + _different_character(character) + _TAIL
            )
            matched += _case_character(character)
        # /api/webhookSomething is not the webhook endpoint or its directory.
        alternatives.append(re.escape(prefix) + matched + _different_character("/") + _TAIL)
    return "^(?:" + "|".join(dict.fromkeys(alternatives)) + ")$" if alternatives else None
