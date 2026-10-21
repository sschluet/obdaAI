"""Source-bound reply-status rendering; model prose cannot invent negative results."""

import re
from typing import Any

from hub.agent_mail_cohort import cohort_evidence, selected_receipt_rows
from hub.agent_models import AgentJob, AgentStep

# A deliberately closed reference/status vocabulary. This is a completion guard,
# never an action classifier or authority grant. Unknown filters, names and verbs
# stay in ordinary planning instead of being declared handled by a cohort table.
_STATUS_WORDS = frozenset(
    """
welche welcher welches welchen was auf von davon denen diese dieser diesen dieses die der den das
habe haben hat ich wir du bereits schon noch sind ist wurde wurden war waren als beantwortet
beantwortete beantworteten beantworteter geantwortet markiert markierte markierten
antwort antworten antwortstatus antwortkennzeichen antwortbeziehung antwortbeziehungen
mails mail e-mails e-mail emails email nachrichten nachricht einträge eintrag meiner meine meinen
unserer unsere vorherigen vorherige zuvor angezeigten angezeigte sichtbaren sichtbare oben
genannten genannte übersicht ausschnitt bitte zeige zeig liste alle mir dazu
which what of those these this the a an any all have has had i i've we you already yet were are
was is been did to as answered replied reply replies status marked messages message emails email
e-mails e-mail mails mail entries entry my our previous previously displayed shown listed above
please show list me
""".split()
)
_STATUS_STARTS = frozenset(
    """
welche welcher welches welchen was auf habe haben hat sind ist wurde wurden war waren
antwortstatus antwortkennzeichen antwortbeziehung antwortbeziehungen beantwortete beantworteten
markierte als zeige zeig liste which what have has had were are was is did reply status
answered replied show list
""".split()
)


def reply_status_goal(goal: str) -> bool:
    """Only closed, single-cohort status questions/lists may finish natively."""
    normalized = " ".join(goal.casefold().split())
    if (
        not normalized
        or ";" in normalized
        or re.search(r"[.!?][.!?\s]*[^.!?\s]", normalized)
        or re.search(
            r"\b(?:und|and|sowie|außerdem|danach|then|anschließend|anschliessend)\b", normalized
        )
        or re.search(r"[^\w\s?.!,:'-]", normalized)
    ):
        return False
    tokens = re.findall(r"\b[\w'-]+\b", normalized)
    if not tokens or any(token not in _STATUS_WORDS for token in tokens):
        return False
    significant = tokens[1:] if tokens[0] in {"bitte", "please"} else tokens
    if not significant or significant[0] not in _STATUS_STARTS:
        return False
    if significant[0] == "reply" and significant[:2] != ["reply", "status"]:
        return False
    if re.search(
        r"\b(?:beantwortet\w*|geantwortet|answered|replied|antwortstatus|reply status|"
        r"antwortkennzeichen|antwortbeziehung\w*)\b",
        normalized,
    ):
        return True
    return bool(
        re.search(r"\b(?:reply|replies|antworten?)\b", normalized)
        and significant[0]
        in {
            "which",
            "what",
            "have",
            "has",
            "were",
            "are",
            "welche",
            "welcher",
            "welches",
            "welchen",
            "was",
            "haben",
            "habe",
            "sind",
            "ist",
        }
    )


def mail_reply_summary(
    db: Any, job: AgentJob, profiles: dict[str, Any], history: list[AgentStep]
) -> str | None:
    """Render only a reconstructed cohort with a current observed Sent query.

    The caller owns intent classification and final cancellation/permission gates.
    This formatter performs fresh receipt revalidation, reads no remote data and
    grants no authority. Unknown or incomplete prerequisites produce no summary.
    """
    from hub.agent_runtime import mail_display

    if not reply_status_goal(job.goal):
        return None
    selected = selected_receipt_rows(db, job, profiles)
    facts = cohort_evidence(db, job, profiles, history)
    rows = facts.get("rows")
    if (
        selected.get("cohort_known") is not True
        or facts.get("cohort_known") is not True
        or facts.get("sent_query_observed") is not True
        or facts.get("cohort_sha256") != selected.get("cohort_sha256")
        or facts.get("source_receipts") != selected.get("source_receipts")
        or not selected["rows"]
        or not isinstance(rows, list)
        or len(rows) != len(selected["rows"])
        or facts.get("displayed_count") != len(rows)
        or facts.get("columns")
        != ["entry", "marked_answered", "flag_refreshed", "sent_relationship"]
        or facts.get("sent_coverage_complete") is not False
        or facts.get("false_flag_means_unanswered") is not False
    ):
        return None
    if any(
        not isinstance(row, list)
        or len(row) != 4
        or type(row[0]) is not int
        or row[0] != ordinal
        or row[1] is not None
        and type(row[1]) is not bool
        or type(row[2]) is not bool
        or row[3] is not None
        and row[3] is not True
        for ordinal, row in enumerate(rows, 1)
    ):
        return None
    positives = sum(row[1] is True for row in rows)
    refreshed = sum(row[2] for row in rows)
    relationships = sum(row[3] is True for row in rows)
    if (
        facts.get("marked_answered_count") != positives
        or facts.get("current_flag_count") != refreshed
        or facts.get("unknown_flag_count") != sum(row[1] is None for row in rows)
    ):
        return None
    lines = [
        f"Von den {len(rows)} zuvor angezeigten Mails sind {positives} als beantwortet markiert "
        "(IMAP Answered).",
        "Die Kennzeichen stammen aus der vorherigen Übersicht (Snapshot), sofern sie unten "
        f"nicht als aktualisiert bezeichnet sind. Im aktuellen Abruf aktualisiert: {refreshed}.",
    ]
    entries = []
    for item, row in zip(selected["rows"], rows, strict=True):
        subject = item["row"].get("subject")
        subject = subject if isinstance(subject, str) and subject else "Ohne Betreff"
        clipped = subject.encode()[:48].decode(errors="ignore")
        subject_text = mail_display(clipped) + (" …" if clipped != subject else "")
        flag = (
            "als beantwortet markiert"
            if row[1] is True
            else "Answered-Kennzeichen nicht gesetzt"
            if row[1] is False
            else "Answered-Kennzeichen unbekannt"
        )
        basis = "aktualisiert" if row[2] else "Stand der vorherigen Übersicht"
        relationship = (
            "Antwortbeziehung im Gesendet-Ordner durch In-Reply-To/References belegt"
            if row[3] is True
            else "Antwortbeziehung im Gesendet-Ordner unbekannt"
        )
        entries.append(f"- Eintrag {row[0]} · {subject_text}: {flag} ({basis}); {relationship}.")
    lines.append("\n".join(entries))
    lines.extend(
        [
            f"Für {relationships} {'Eintrag' if relationships == 1 else 'Einträge'} ist "
            "im aktuellen begrenzten Abruf eine gespeicherte "
            "Antwortbeziehung im Gesendet-Ordner belegt. "
            "Der Gesendet-Ordner wurde im aktuellen Lauf begrenzt abgefragt und "
            "nicht vollständig geprüft; "
            "fehlende Antwortbeziehungen bleiben unbekannt.",
            "Ein fehlendes Kennzeichen ist kein Nachweis für unbeantwortet. "
            "Die Anzeige bezieht sich nur auf den vorherigen Ausschnitt und bestätigt weder "
            "die Vollständigkeit des Postfachs noch die Zustellung einer Antwort.",
        ]
    )
    return "\n\n".join(lines)
