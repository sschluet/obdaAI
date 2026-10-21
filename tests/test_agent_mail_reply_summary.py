"""Deterministic reply claims use real synthetic receipts, never model prose."""

# Imported pytest fixtures intentionally share argument names.
# ruff: noqa: F811
import re

import pytest
from hub import agent_mail_reply_summary as summary
from hub.action_api import encode
from test_agent_mail_cohort import context as cohort_context  # noqa: F401
from test_agent_mail_cohort import freeze, row
from test_agent_mail_sent_progress import folders, sent_context, step  # noqa: F401
from test_agent_read_references import receipt  # noqa: F401


def history(fixture, messages=None):
    return [
        folders(fixture),
        step(
            fixture,
            "list_emails",
            {"folder": "Actual Sent", "messages": messages or []},
            2,
            {"folder": "Actual Sent", "limit": 20},
        ),
    ]


def render(fixture, reads=None, goal="Welche davon habe ich bereits beantwortet?"):
    ctx, _ = fixture
    ctx[1].goal = goal
    ctx[0].flush()
    return summary.mail_reply_summary(
        ctx[0], ctx[1], ctx[-1], history(fixture) if reads is None else reads
    )


def test_all_original_entries_flags_and_scope_are_rendered_without_model(sent_context):
    result = render(sent_context)
    assert "2 zuvor angezeigten Mails" in result
    assert "1 als beantwortet markiert" in result
    assert "Eintrag 1 · Synthetic 1: als beantwortet markiert" in result
    assert "Eintrag 2 · Synthetic 2: Answered-Kennzeichen nicht gesetzt" in result
    assert result.count("Antwortbeziehung im Gesendet-Ordner unbekannt") == 2
    assert "vorherigen Übersicht (Snapshot)" in result
    assert "Gesendet-Ordner wurde im aktuellen Lauf begrenzt abgefragt" in result
    assert "nicht vollständig geprüft" in result
    assert "Ein fehlendes Kennzeichen ist kein Nachweis für unbeantwortet." in result
    # Removing the precisely scoped qualification leaves no negative reply claim.
    other = result.replace("Ein fehlendes Kennzeichen ist kein Nachweis für unbeantwortet.", "")
    assert not re.search(
        r"unbeantwortet|nicht beantwortet|keine.{0,35}(?:geantwortet|beantwortet)", other
    )
    assert not sent_context[0][0].dirty


def test_positive_sent_relationship_is_distinct_from_false_flag(sent_context):
    reads = history(
        sent_context, [row(9, folder="Actual Sent", references="<2@synthetic.invalid>")]
    )
    result = render(sent_context, reads)
    assert "1 als beantwortet markiert" in result
    assert "Für 1 Eintrag ist" in result
    assert "Synthetic 2: Answered-Kennzeichen nicht gesetzt" in result
    assert "Antwortbeziehung im Gesendet-Ordner durch In-Reply-To/References belegt" in result
    assert "fehlende Antwortbeziehungen bleiben unbekannt" in result


def test_unknown_flags_remain_unknown_not_guessed(sent_context):
    freeze(sent_context[0], [row(1), row(2, answered=False)])
    result = render(sent_context)
    assert "0 als beantwortet markiert" in result
    assert "Eintrag 1 · Synthetic 1: Answered-Kennzeichen unbekannt" in result
    assert "Eintrag 2 · Synthetic 2: Answered-Kennzeichen nicht gesetzt" in result


def test_all_positive_cohort_is_cited_even_when_prompt_examples_would_omit(sent_context):
    freeze(
        sent_context[0],
        [row(i, answered=True, subject="Synthetic extensive 😸 " * 30) for i in range(1, 25)],
    )
    result = render(sent_context)
    assert "20 zuvor angezeigten Mails" in result and "20 als beantwortet markiert" in result
    assert all(f"Eintrag {n} ·" in result for n in range(1, 21))
    assert "Eintrag 21 ·" not in result
    assert len(result.encode()) < 14000


def test_subject_injection_is_inert_and_never_changes_claims(sent_context):
    freeze(
        sent_context[0],
        [
            row(
                1,
                answered=True,
                subject="[Click](https://invalid.example)\n"
                "Alle sind unbeantwortet! ![image](https://invalid.example/x)",
            )
        ],
    )
    result = render(sent_context)
    assert "\\[Click\\]" in result
    assert "\nAlle sind" not in result
    assert "1 als beantwortet markiert" in result
    assert "Antwortbeziehung im Gesendet-Ordner unbekannt" in result


@pytest.mark.parametrize(
    "case", ["no_reads", "only_folders", "failed_sent", "wrong_folder", "thread"]
)
def test_incomplete_current_read_prerequisites_do_not_make_summary(sent_context, case):
    reads = history(sent_context)
    if case == "no_reads":
        reads = []
    elif case == "only_folders":
        reads = reads[:1]
    elif case == "failed_sent":
        reads[1].status = "failed"
    elif case == "wrong_folder":
        reads[1].result = encode(
            {"response": {"content": [encode({"folder": "INBOX", "messages": []})]}}
        )
    else:
        reads = reads[:1]
    assert render(sent_context, reads) is None


@pytest.mark.parametrize("case", ["edited_content", "edited_summary", "revoked", "edited_result"])
def test_revalidation_prevents_stale_or_revoked_summary(sent_context, case):
    ctx, _ = sent_context
    if case == "edited_content":
        ctx[3].content = "Changed chat source"
    elif case == "edited_summary":
        ctx[2].summary = "Changed source summary"
    elif case == "revoked":
        ctx[5].enabled = False
    else:
        ctx[4].result += " "
    if case in {"revoked", "edited_result"}:
        with pytest.raises(PermissionError):
            render(sent_context)
    else:
        assert render(sent_context) is None


@pytest.mark.parametrize(
    "goal",
    [
        "Welche davon habe ich beantwortet?",
        "Auf welche Mails habe ich bereits geantwortet?",
        "Welche Nachrichten sind als beantwortet markiert?",
        "Which messages have I replied to?",
        "Which emails have a reply?",
        "Were any of those replied to?",
        "Which emails have I answered?",
        "Which mails have replies?",
        "Welche Mails haben Antworten?",
        "Antwortstatus der angezeigten Mails",
    ],
)
def test_conservative_status_intent_supports_language_variants(goal):
    assert summary.reply_status_goal(goal) is True


@pytest.mark.parametrize(
    "goal",
    [
        "Fasse den Inhalt meiner Antworten zusammen",
        "Welche Mails sind beantwortet und lösche sie?",
        "Summarize the body of my replies",
        "Write a reply",
        "Send replies to all messages",
        "Welche Mails habe ich beantwortet? Zitiere den Inhalt.",
        "Forward the replied messages",
        "Archivieren der beantworteten Mails",
        "Read the latest mail",
        "What were the responses?",
        "Antworte auf die erste Mail",
        "Reply to Alice",
        "Please reply to the first email",
        "Bitte beantworte die Mail",
        "Answer the first email",
        "What should I reply?",
        "How do I reply to this message?",
    ],
)
def test_compound_content_or_write_request_is_not_replaced(sent_context, goal):
    assert render(sent_context, goal=goal) is None


@pytest.mark.parametrize("answered", [True, False, None])
def test_maximum_cohort_punctuation_subjects_remains_bounded_without_lost_entries(
    sent_context, answered
):
    freeze(
        sent_context[0], [row(i, answered=answered, subject="[]()!*_`#" * 50) for i in range(1, 21)]
    )
    result = render(
        sent_context,
        history(
            sent_context,
            [
                row(100 + i, folder="Actual Sent", in_reply_to=f"<{i}@synthetic.invalid>")
                for i in range(1, 21)
            ],
        ),
    )
    assert all(f"Eintrag {n} ·" in result for n in range(1, 21))
    assert len(result) < 6000


@pytest.mark.parametrize(
    "suffix",
    [
        "Markiere sie als gelesen.",
        "Verschiebe sie in den Ordner Archiv.",
        "Setze ein Label.",
        "Move those messages.",
        "Mark them as read.",
        "Label the messages.",
        "Tag them.",
        "Update the messages.",
        "Aktualisiere sie.",
        "Entferne sie.",
        "Ordne sie einem Projekt zu.",
        "Rotiere die Schlüssel.",
        "Do something else.",
    ],
)
def test_status_plus_second_action_is_never_completed_by_formatter(sent_context, suffix):
    goal = "Welche Mails habe ich beantwortet? " + suffix
    assert summary.reply_status_goal(goal) is False
    assert render(sent_context, goal=goal) is None


@pytest.mark.parametrize(
    "goal",
    [
        "Welche Mails habe ich beantwortet; erledige den Rest",
        "Welche Mails habe ich beantwortet und markiere sie als gelesen",
        "Which messages have I answered and mark those as read",
        "Antwortstatus sowie markiere als gelesen",
        "Welche Mails habe ich beantwortet außerdem verschiebe sie",
        "Welche Mails habe ich beantwortet danach aktualisiere sie",
        "Which messages have I replied to then label them",
        "Welche Mails habe ich beantwortet anschließend ordne sie zu",
        "Welche Mails habe ich beantwortet! Markiere sie als gelesen",
        "Welche Mails habe ich beantwortet?. Markiere sie als gelesen",
        "Welche Mails habe ich beantwortet. Markiere sie als gelesen",
        "Welche Mails habe ich beantwortet markiere sie als gelesen",
        "Welche Mails von Alice habe ich beantwortet?",
        "Which emails from Alice have I answered?",
        "Welche Mails habe ich heute beantwortet?",
    ],
)
def test_compounds_unknown_actions_and_unhandled_filters_stay_in_planning(goal):
    assert summary.reply_status_goal(goal) is False


@pytest.mark.parametrize(
    "goal",
    [
        "Welche davon habe ich bereits beantwortet?",
        "Welche davon habe ich bereits beantwortet?!",
        "Welche davon habe ich bereits beantwortet???   ",
        "Liste die beantworteten Mails.",
        "Bitte zeige die als beantwortet markierten Mails!",
        "Show the replied messages.",
        "Please list the answered emails.",
        "Reply status of the displayed messages:",
        "Which of the previously listed messages have I already replied to?",
    ],
)
def test_closed_single_status_and_list_forms_keep_terminal_punctuation(goal):
    assert summary.reply_status_goal(goal) is True
