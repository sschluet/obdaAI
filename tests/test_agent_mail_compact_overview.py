"""Compact observed results preserve old cohort contracts and hide unresolved dates."""

import json

import pytest
from hub import agent_mail_cohort as cohort
from hub.agent_runtime import mail_overview_summary
from test_agent_mail_cohort import context, freeze, row  # noqa: F401
from test_agent_mail_evidence import CLOCK, GOAL, header
from test_agent_mail_evidence import receipt as header_receipt
from test_agent_read_references import receipt  # noqa: F401


def test_compact_overview_resolves_offset_and_header_fallback_without_technical_footer():
    unknown = header("Unresolved mail", received="2026-10-20T13:00:00", uid=1)
    fallback = header("Resolved header", received="invalid",
                      date="Tue, 20 Oct 2026 10:00:00 +0000", uid=2)
    regular = header("Received mail", received="2026-10-20T11:00:00+00:00", uid=3)
    text = mail_overview_summary([header_receipt([unknown, fallback, regular])], CLOCK, GOAL, {})
    assert "Resolved header" in text and "Received mail" in text
    assert "Unresolved mail" not in text
    assert "20.10.2026, 12:00" in text and "20.10.2026, 13:00" in text
    assert "Received mail" in text[:text.index("Resolved header")]
    for technical in ("Abfrageumfang", "Kopfzeilen", "Header-Datum", "unsicher",
                      "Vollständigkeit", "Zeitzone", "INBOX", "ausgelassen"):
        assert technical not in text


def test_compact_empty_selection_does_not_claim_empty_mailbox_or_display_unknown_rows():
    text = mail_overview_summary([header_receipt([header("Unresolved", received="unknown")])],
                                 CLOCK, GOAL, {})
    assert text == "In den abgerufenen Nachrichten wurden keine passenden Mails gefunden."
    assert "Unresolved" not in text


def test_compact_overview_is_bounded_and_treats_subjects_as_inert_text():
    rows = [header("<img src=x> [link](https://remote.invalid/)", uid=1)]
    rows += [header(f"Synthetic mail {i}", uid=i) for i in range(2, 28)]
    text = mail_overview_summary([header_receipt(rows)], CLOCK, GOAL, {})
    assert text.count("\n- ") == 20
    assert "<img" not in text.replace("\\<img", "") and "[link](" not in text
    assert "https://" not in text and "Synthetic mail 21" not in text


@pytest.mark.parametrize("version", [1, 2])
def test_source_cohort_uses_saved_renderer_and_keeps_legacy_unknown_rows(context, version):  # noqa: F811
    db, job, source, message, _, _, _, profiles = context
    binding = json.loads(source.bindings)
    binding["clock"]["timezone"] = "Europe/Berlin"
    if version == 2:
        binding["mail_overview_version"] = 2
    else:
        binding.pop("mail_overview_version", None)  # Actual pre-release persisted sources.
    source.bindings = json.dumps(binding)
    freeze(context, [row(1), row(2, received="unknown")])
    selected = cohort.selected_receipt_rows(db, job, profiles)
    assert selected["cohort_known"] is True
    assert [item["row"]["uid"] for item in selected["rows"]] == ([1, 2] if version == 1 else [1])
    assert ("Datum nicht sicher" in message.content) is (version == 1)
    # A different presentation contract cannot reinterpret the displayed cohort.
    binding["mail_overview_version"] = 3 - version
    source.bindings = json.dumps(binding)
    db.flush()
    assert cohort.selected_receipt_rows(db, job, profiles)["cohort_known"] is False
