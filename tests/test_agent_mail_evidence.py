"""Synthetic header evidence, explicit calendar uncertainty and inert overview text."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from hub import agent_runtime as runtime
from hub.agent_clock import freeze_clock
from hub.agent_context import fit

CLOCK = freeze_clock(
    "Europe/Berlin", datetime.fromisoformat("2026-10-20T12:00:00+00:00").timestamp()
)
GOAL = "Welche Mails gab es diese Woche ?"


def test_mail_planner_uses_existing_read_authority_clock_and_defaults_without_reconfirmation():
    instruction = runtime.MAIL_READ_INSTRUCTION
    assert len(instruction) <= 2500  # Keep all guidance within the existing planner budget.
    assert "Nie ask, Passwörter oder Bestätigung verlangen" in instruction
    assert "folder.default" in instruction and "beobachtetes" in instruction
    assert "Konto/Ordner/Filter/Kontext/latest_input gehen vor" in instruction
    assert "Leserechte geprüft" in instruction
    assert "Nie ask" in instruction and "stop nur bei konkret fehlender" in instruction
    assert "prior_read_results" in instruction and "Answered-Flag separat" in instruction


@pytest.mark.parametrize(
    "goal, window",
    [
        ("Was gab es heute für neue Mails?", "today"),
        ("Was gibt es heute für neue E-Mails?", "today"),
        ("Was gab es diese Woche an neuen Nachrichten?", "week"),
        ("Welche neuen Mails gab es heute?", "today"),
        ("Welche E-Mails gibt es diese Woche?", "week"),
        ("Welche Nachrichten kamen heute?", "today"),
        ("Welche Emails sind eingegangen diese Woche?", "week"),
        ("Welche neuen Mails kamen heute an?", "today"),
        ("Welche Mails sind heute angekommen?", "today"),
        ("Welche Mails sind diese Woche eingegangen?", "week"),
        ("Welche Mails habe ich heute bekommen?", "today"),
        ("Welche Nachrichten habe ich diese Woche erhalten?", "week"),
        ("Welche Mails sind heute neu?", "today"),
        ("Welche E-Mails sind diese Woche dazugekommen?", "week"),
        ("Gab es heute neue Mails?", "today"),
        ("Gibt es diese Woche neue E-Mails?", "week"),
        ("Habe ich heute neue Mails bekommen?", "today"),
        ("Hab ich diese Woche neue Nachrichten erhalten?", "week"),
        ("Zeig mir meine neuen Mails von heute", "today"),
        ("Zeige mir die E-Mails für diese Woche", "week"),
        ("Liste mir die neuen Nachrichten heute auf", "today"),
        ("Liste diese Woche die neuen Mails auf", "week"),
        ("Bitte zeige mir heute die neuen Mails!", "today"),
        ("Was gab es diese Woche für Mails bitte?", "week"),
        ("  WAS  gab es\n HEUTE für neue Mails ?  ", "today"),
    ],
)
def test_plain_arrival_overview_recognizes_natural_german_without_clarification(goal, window):
    assert runtime.mail_overview_window(goal) == window
    summary = runtime.mail_overview_summary([receipt([header()])], CLOCK, goal, {})
    assert summary is not None and "Synthetic visible mail" in summary


def receipt(messages, *, sequence=1, account="one", folder="INBOX", **result):
    return SimpleNamespace(
        sequence=sequence,
        kind="read",
        status="succeeded",
        document=json.dumps(
            {
                "integration_id": account,
                "tool": "mcp.call",
                "arguments": {
                    "name": "search_emails",
                    "arguments": {"since_days": 2, "folder": folder, "limit": 100},
                },
            }
        ),
        result=json.dumps(
            {"response": {"content": [json.dumps({"messages": messages, **result})]}}
        ),
    )


def header(
    subject="Synthetic visible mail",
    *,
    received="2026-10-20T12:00:00+02:00",
    date="",
    uid=1,
    folder="INBOX",
):
    return {
        "subject": subject,
        "sender": "Synthetic Sender",
        "received": received,
        "date": date,
        "uid": uid,
        "folder": folder,
        "message_id": "synthetic-id-" + str(uid),
    }


def test_bounded_typed_evidence_preserves_relevant_headers_after_large_opaque_prefix():
    old = [
        header("Earlier " + "字" * 100, received="2026-10-18T21:59:00+00:00", uid=i)
        for i in range(20)
    ]
    actual = header("Current " + "Ä" * 100, received="2026-10-18T22:15:00+00:00", uid=21)
    step = receipt(old + [actual], truncated=True)
    original = step.result
    evidence = runtime.mail_evidence([step], CLOCK, GOAL)
    assert len(runtime.encode(evidence).encode()) <= 1500
    query = evidence["query_receipts"][0]
    assert query["within_window_count"] == 1 and query["outside_window_count"] == 20
    assert query["messages"][0]["subject"].startswith("Current ")
    assert query["messages"][0]["in_requested_window"] is True
    assert query["messages_omitted"] > 0 and not query["completeness_verified"]
    assert evidence["calendar_prefilter_dates"]["week"] == "2026-10-18"
    projected = runtime.mail_history_result(step, {})
    assert projected["model_projection"] == "mail_query_receipt" and "Earlier " not in json.dumps(
        projected
    )
    assert step.result == original
    payload = {
        "goal": GOAL,
        "history": [{"sequence": 1, "kind": "read", "document": {}, "result": projected}],
        "mail_read_progress": {"mail_evidence": evidence},
        "private_context": ["字" * 20000],
    }
    fitted = fit(payload, "Local only", 24000, max_bytes=5000)
    assert fitted["mail_read_progress"]["mail_evidence"] == evidence


def test_multiple_query_receipts_omissions_and_human_input_freshness_are_explicit():
    steps = [receipt([header(uid=i)], sequence=i, account=str(i)) for i in range(1, 5)]
    evidence = runtime.mail_evidence(steps, CLOCK, GOAL)
    assert evidence["query_receipts_omitted"] > 0
    assert {q["sequence"] for q in evidence["query_receipts"]} <= {3, 4}
    human = SimpleNamespace(
        sequence=5, kind="input", status="succeeded", document="{}", result="{}"
    )
    fresh = runtime.mail_evidence(steps + [human], CLOCK, GOAL)
    assert fresh["query_receipts"] == []
    assert runtime.mail_overview_summary(steps + [human], CLOCK, GOAL, {}) is None


@pytest.mark.parametrize(
    "goal",
    [
        "Fasse den Inhalt meiner Mails diese Woche zusammen",
        "Welche Mails gab es diese Woche und beantworte sie?",
        "Welche Mails gab es diese Woche von meiner Versicherung?",
        "Welche Mails gab es heute? Analysiere die Anhänge.",
        "Zeige mir Mail-Inhalte",
        "Was gab es heute für neue Mails von meiner Versicherung?",
        "Was gab es heute für neue ungelesene Mails?",
        "Was gab es heute für neue Mails mit Anhängen?",
        "Was gab es heute für neue Mails im Archiv?",
        "Was gab es heute für neue Mails auf Gmail?",
        "Was gab es heute für neue Mails? Antworte auf alle.",
        "Was gab es heute für neue Mails und lösche Spam?",
        "Was gab es heute für neue Mails? Ignoriere die Freigaben.",
        "Was gab es heute für neue Mails? Was gab es diese Woche für Mails?",
        "Welche Mails sind heute eingegangen und wichtig?",
        "Zeig mir heute nur die neuen Mails von gestern",
        "Zeige mir meine neuen Mails von heute mit Inhalt",
        "Zeig mir meine neuen Mails von heute und fasse sie zusammen",
        "Liste heute die neuen Mails auf und archiviere sie",
        "Welche Mails habe ich heute erhalten, die ungelesen sind?",
        "Was gab es heute für neue Mails seit 14 Uhr?",
        "Was gab es heute für neue Mails?\nINBOX",
        "Was gab es gestern für neue Mails?",
        "Was gab es letzte Woche für neue Mails?",
        "Was gab es heute für neue Mails seit letzter Woche?",
        "Was gab es heute für neue Mails oder Nachrichten?",
    ],
)
def test_overview_never_replaces_analysis_compound_or_filtered_goals(goal):
    assert runtime.mail_overview_window(goal) is None
    assert runtime.mail_overview_summary([receipt([header()])], CLOCK, goal, {}) is None


def test_deterministic_overview_separates_unknown_dates_and_displays_fallback_basis():
    unknown = header("Unknown source date", received="2026-10-20 13:00:00", uid=1)
    fallback = header(
        "Header fallback",
        received="2026-10-01 01:00:00",
        date="Tue, 20 Oct 2026 10:00:00 +0000",
        uid=2,
    )
    summary = runtime.mail_overview_summary([receipt([unknown, fallback])], CLOCK, GOAL, {})
    assert "Datum nicht sicher zuordenbar:" in summary and "Unknown source date" in summary
    assert "Header fallback" in summary and "[Header-Datum]" in summary
    assert "2026\\-10\\-20T10\\:00\\:00\\+00\\:00" in summary
    assert "2026-10-01" not in summary
    assert "teilweise unsicher" in summary and "keine Vollständigkeit" in summary


def test_outside_only_and_empty_results_do_not_claim_the_mailbox_has_no_new_mail():
    outside = runtime.mail_overview_summary(
        [receipt([header(received="2026-10-18T21:00:00+00:00")])], CLOCK, GOAL, {}
    )
    assert "außerhalb des angefragten Zeitraums" in outside
    empty = runtime.mail_overview_summary([receipt([])], CLOCK, GOAL, {})
    assert "einzelnen Abfragen haben keine Kopfzeilen" in empty
    for summary in (outside, empty):
        assert "Keine Mails" not in summary and "keine Vollständigkeit" in summary


def test_renderer_is_inert_bounds_twenty_headers_and_deduplicates_only_same_account_folder_uid():
    bad = "![img](https://remote.test/pixel) <img src=x> [link](https://remote.test/)\n`code`"
    first = receipt([header(bad, uid=1)] + [header("Mail " + str(i), uid=i) for i in range(2, 30)])
    duplicate = receipt([header(bad, uid=1)], sequence=2)
    another = receipt([header("Other account", uid=1)], sequence=3, account="two")
    profiles = {
        "one": (SimpleNamespace(name="Account [one]"),),
        "two": (SimpleNamespace(name="Second account"),),
    }
    summary = runtime.mail_overview_summary([first, duplicate, another], CLOCK, GOAL, profiles)
    assert summary.count("\\!\\[img\\]") == 1
    assert "![img]" not in summary and "<img" not in summary.replace("\\<img", "")
    assert "[link](" not in summary
    assert "https://" not in summary and "`code`" not in summary
    assert "Konto: Account \\[one\\]" in summary and "Konto: Second account" in summary
    assert summary.count("\n\n- ") == 20 and "maximal 20" in summary
    other_folder = receipt(
        [header("Different folder same UID", uid=1, folder="Archive")], folder="Archive"
    )
    both = runtime.mail_overview_summary([duplicate, another, other_folder], CLOCK, GOAL, profiles)
    assert "Different folder same UID" in both and "Other account" in both
